import decimal

from django.db import transaction
from django.db.models import Q, Avg, Sum, Count
from django.shortcuts import render, get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Rider
from multi_orders.custom_mixins import MultiRiderOrderErrorHandlingMixin
from multi_orders.models import OrderRiderAssignment, Feedback
from orders.models import Order, DeclinedOrder
from django.utils import timezone
from accounts.utils import (
    DistanceCalculator,
    generate_otp,
    send_customer_notification,
    send_riders_notification,
    str_to_bool,
)
from orders.serializers import OrderDetailSerializer
from map_clients.map_clients import MapClientsManager, get_distance
from map_clients.supabase_query import SupabaseTransactions
import logging

from wallet.models import WalletTransaction, PendingWalletTransaction

map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

logger = logging.getLogger(__name__)

# Create your views here.


class AcceptOrDeclineOrderAssignmentView(APIView, MultiRiderOrderErrorHandlingMixin):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        try:
            order_id = request.data.get('order_id')
            accept = request.data.get('accept', False)
            reason = request.data.get("reason", '')

            rider = request.user.rider_profile
            order_assignment = get_object_or_404(
                OrderRiderAssignment,
                order_id=order_id,
                rider=rider
            )

            if accept:
                order_assignment.status = 'Accepted'
                order_assignment.save()

                """Update overall order status based on rider assignments."""
                assignments = order_assignment.order.orderriderassignment_set.all()

                if all(assignment.status == 'Accepted' for assignment in assignments):
                    order_assignment.order.status = 'Assigned'
                elif any(assignment.status == 'Accepted' for assignment in assignments):
                    order_assignment.order.status = 'PartiallyAssigned'

                order_assignment.order.save()

            else:
                order_assignment.status = 'Declined'
                order_assignment.save()

                rider.declined_requests += 1
                rider.save()
                # Create and save DeclinedOrder instance
                DeclinedOrder.objects.create(
                    order=order_assignment.order,
                    customer=None,
                    rider=rider,
                    decline_reason=reason,
                )
                self.find_replacement_rider(order_assignment)

            return Response({'message': 'Order status updated'})

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def find_replacement_rider(self, declined_assignment):
        """
        Find a replacement rider for a declined order assignment

        Args:
            declined_assignment (OrderRiderAssignment): The declined rider assignment

        Returns:
            Rider or None: A suitable replacement rider
        """
        order = declined_assignment.order
        declined_weight = declined_assignment.assigned_weight

        # Logging the replacement process
        logger.info(
            f"Initiating replacement rider search for Order {order.id}",
            extra={
                'order_id': order.id,
                'declined_rider_email': declined_assignment.rider.user.email,
                'declined_weight': float(declined_weight)
            }
        )

        # Find alternative riders who can handle the declined weight
        alternative_riders = Rider.objects.filter(
            Q(max_capacity__gte=declined_weight) &  # Can handle the weight
            Q(min_capacity__lte=declined_weight) &  # Minimum capacity check
            Q(fragile_item_allowed=order.fragile) &  # Fragile item handling
            ~Q(id=declined_assignment.rider.id)  # Exclude the original declined rider
        ).exclude(
            # Exclude riders already assigned to this order
            id__in=order.riders.values_list('id', flat=True)
        )

        # Prioritize riders based on proximity and availability
        try:
            pickup_location = f"{order.pickup_long},{order.pickup_lat}"

            # Use distance calculation to find the closest suitable rider
            fields = ["rider_email", "current_lat", "current_long"]
            riders_location_data = supabase.get_supabase_riders(fields=fields)

            distance_calculator = DistanceCalculator(pickup_location)

            # Filter and sort riders by proximity
            nearby_suitable_riders = [
                rider for rider in riders_location_data
                if rider['email'] in alternative_riders.values_list('user__email', flat=True)
            ]

            nearby_suitable_riders.sort(
                key=lambda r: distance_calculator.calculate_distance(
                    f"{r['current_long']},{r['current_lat']}"
                )
            )

            if nearby_suitable_riders:
                closest_rider_email = nearby_suitable_riders[0]['email']
                replacement_rider = Rider.objects.get(user__email=closest_rider_email)

                # Create new rider assignment
                new_assignment = OrderRiderAssignment.objects.create(
                    order=order,
                    rider=replacement_rider,
                    assigned_weight=declined_weight,
                    status='Pending'
                )

                # Notify the replacement rider
                send_riders_notification.delay(
                    riders=[replacement_rider],
                    order_id=order.id,
                    assigned_weight=declined_weight,
                    replacement_notification=True
                )

                # Logging successful replacement
                logger.info(
                    f"Replacement rider found for Order {order.id}",
                    extra={
                        'order_id': order.id,
                        'replacement_rider_email': replacement_rider.user.email,
                        'assigned_weight': float(declined_weight)
                    }
                )

                return replacement_rider

        except Exception as e:
            # Comprehensive error handling for replacement process
            logger.error(
                f"Error finding replacement rider for Order {order.id}",
                extra={
                    'order_id': order.id,
                    'error_type': type(e).__name__,
                    'error_details': str(e)
                }
            )

            # Escalate if no replacement found
            self.handle_order_assignment_errors(
                order,
                'partial_assignment_failure'
            )

            return None


class BulkOrderAssignmentView(APIView):
    """
    View for bulk assignment of orders to riders, supporting splitting orders among multiple riders.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        rider_emails = request.data.get("rider_emails", [])
        order_ids = request.data.get("order_ids", [])
        price = request.data.get("price")

        wallet = request.user.wallet

        if wallet.balance < decimal.Decimal(price):
            return Response(
                {"error": "Insufficient balance"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not rider_emails or not order_ids:
            return Response(
                {"error": "Rider emails and order IDs are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(rider_emails) > len(order_ids):
            return Response(
                {"error": "More riders provided than orders to assign."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Fetch orders and validate
            orders = Order.objects.filter(id__in=order_ids, status="Pending")
            if len(orders) != len(order_ids):
                return Response(
                    {"error": "Some orders are invalid or not in a pending state."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            riders = Rider.objects.filter(user__email__in=rider_emails)
            if len(riders) != len(rider_emails):
                return Response(
                    {"error": "Some riders are invalid or not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Assign orders to riders
            successful_assignments = []
            failed_assignments = []
            rider_queue = iter(riders)  # Create an iterator for cycling through riders

            # Assign each order to a rider
            for order in orders:
                try:
                    rider = next(rider_queue)
                except StopIteration:
                    rider_queue = iter(riders)  # Reset the iterator if we run out of riders
                    rider = next(rider_queue)

                self.assign_order_to_rider(order, rider, successful_assignments, failed_assignments)

            # Prepare response
            response_data = {
                "message": "Bulk order assignment completed.",
                "successful_assignments": successful_assignments,
                "failed_assignments": failed_assignments,
            }
            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Bulk order assignment failed: {str(e)}")
            transaction.set_rollback(True)
            return Response(
                {"error": "An unexpected error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def assign_order_to_rider(self, order, rider, successful_assignments, failed_assignments):
        try:
            order_location = f"{order.pickup_long},{order.pickup_lat}"
            conditions = [{"column": "rider_email", "value": rider.user.email}]
            fields = ["rider_email", "current_lat", "current_long"]

            rider_data = supabase.get_supabase_riders(
                conditions=conditions, fields=fields
            )

            try:
                result = self.get_matrix_results(order_location, rider_data)
            except Exception as e:
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                result = self.get_matrix_results(order_location, rider_data)

            distance = result[0]["distance"]
            duration = result[0]["duration"]

            code = generate_otp(length=4)

            order.rider = rider
            order.status = "WaitingForPickup"
            order.distance = distance
            order.duration = duration
            order.price = decimal.Decimal(order.price) * 100  # Assuming price per order
            order.order_completion_code = code
            order.save()

            PendingWalletTransaction.objects.create(
                user=self.request.user, order=order, amount=order.price / 100
            )

            successful_assignments.append(
                {
                    "order_id": order.id,
                    "rider_email": rider.user.email,
                    "distance": distance,
                    "duration": duration,
                    "code": code,
                }
            )
        except Exception as e:
            logger.error(f"Failed to assign order {order.id} to rider {rider.user.email}: {str(e)}")
            failed_assignments.append(
                {"order_id": order.id, "rider_email": rider.user.email, "error": str(e)}
            )

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class UpdateBulkOrderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        orders_data = request.data.get("orders", [])

        if not orders_data:
            return Response(
                {"error": "Orders data is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        successful_updates = []
        failed_updates = []

        for order_data in orders_data:
            order_id = order_data.get("order_id")
            order_status = order_data.get("status")
            order_code = order_data.get("order_code")

            if not order_id or not order_status:
                failed_updates.append(
                    {
                        "order_id": order_id,
                        "error": "Both order_id and status are required.",
                    }
                )
                continue

            if order_status not in valid_statuses:
                failed_updates.append(
                    {
                        "order_id": order_id,
                        "error": f"Invalid status: {order_status}",
                    }
                )
                continue

            try:
                order = Order.objects.get(id=order_id)

                if order_status == "Delivered":
                    if not order_code:
                        failed_updates.append(
                            {
                                "order_id": order_id,
                                "error": "order_code is required for Delivered status.",
                            }
                        )
                        continue

                    if order.order_completion_code != order_code:
                        failed_updates.append(
                            {
                                "order_id": order_id,
                                "error": "Invalid order code.",
                            }
                        )
                        continue

                order.status = order_status
                order.save()

                send_customer_notification(
                    customer=order.customer.user.email,
                    message=f"Status update {order_status}",
                    ride_status=order_status,
                    by_pass_rider_info=True,
                )

                successful_updates.append(
                    {
                        "order_id": order_id,
                        "status": order_status,
                    }
                )

            except Order.DoesNotExist:
                failed_updates.append(
                    {"order_id": order_id, "error": "Order not found."}
                )

            except Exception as e:
                logger.error(f"Error updating order {order_id}: {str(e)}")
                failed_updates.append(
                    {"order_id": order_id, "error": str(e)}
                )

        response_data = {
            "message": "Bulk order status update completed.",
            "successful_updates": successful_updates,
            "failed_updates": failed_updates,
        }
        return Response(response_data, status=status.HTTP_200_OK)


class RealTimeOrderTrackingView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5

    def get(self, request, order_id, *args, **kwargs):
        try:
            order = get_object_or_404(Order, id=order_id)
            riders = order.riders.all()  # Fetch all associated riders

            riders_data = []
            for rider in riders:
                # Fetch assignment for the current rider and order
                assignments = OrderRiderAssignment.objects.filter(order=order, rider=rider, customer=request.user)
                for assignment in assignments:
                    # Calculate distance and ETA
                    result = self.get_additional_information(order, rider)

                    distance = result[0]["distance"]
                    duration = result[0]["duration"]

                    # distance_to_destination = get_distance(
                    #     f"{rider.current_long},{rider.current_lat}",
                    #     f"{order.recipient_long},{order.recipient_lat}"
                    # )
                    # eta = round((distance_to_destination / 40) * 60)  # Assuming 40km/h average speed

                    # Append rider data
                    riders_data.append({
                        "email": rider.user.email,
                        "name": rider.user.get_full_name(),
                        "assignment_status": assignment.status,
                        "rider_status": rider.status,
                        "rider_location": {
                            "lat": rider.current_lat,
                            "long": rider.current_long
                        },
                        "distance_to_destination": f"{distance} km",
                        "eta": f"{duration} minutes",
                    })

            # Serialize order details
            serializer = OrderDetailSerializer(order)
            return Response({**serializer.data, "riders": riders_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in tracking order {order_id}: {str(e)}")
            return Response({"error": "Could not fetch tracking details."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_additional_information(self, order, rider):
        order_location = f"{order.pickup_long},{order.pickup_lat}"
        conditions = [{"column": "rider_email", "value": rider.user.email}]
        fields = ["rider_email", "current_lat", "current_long"]

        rider_data = supabase.get_supabase_riders(
            conditions=conditions, fields=fields
        )

        try:
            result = self.get_matrix_results(order_location, rider_data)
        except Exception as e:
            logger.error(f"Error processing API request: {str(e)}")
            map_clients_manager.switch_client()
            result = self.get_matrix_results(order_location, rider_data)

        return result

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class BulkOrderSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        """
        Comprehensive order tracking and reporting endpoint
        Provides detailed insights into multi-rider order status
        """
        try:
            bulk_order = get_object_or_404(Order, id=order_id, is_bulk=True)
            assignments = OrderRiderAssignment.objects.filter(order=bulk_order, customer=request.user)

            summary = [
                {
                    "id": assignment.id,
                    "destination": {
                        "lat": assignment.recipient_lat,
                        "long": assignment.recipient_long,
                    },
                    "status": assignment.status,
                    'assigned_weight': assignment.assigned_weight,
                    'rider_capacity': {
                        'min_capacity': assignment.rider.min_capacity,
                        'max_capacity': assignment.rider.max_capacity
                    },
                    "rider": assignment.rider.user.get_full_name() if assignment.rider else None
                }
                for assignment in assignments
            ]

            # Logging the report generation
            logger.info(f"Order {order_id} report generated",
                        extra={
                            'order_id': order_id,
                            'total_riders': len([assignment.rider for assignment in assignments]),
                            'fulfilled_percentage': (bulk_order.fulfilled_weight / bulk_order.total_weight) * 100
                        })

            return Response(
                {
                    "bulk_order_id": bulk_order.id,
                    "total_weight": bulk_order.total_weight,
                    'fulfilled_weight': bulk_order.fulfilled_weight,
                    "remaining_weight": bulk_order.remaining_weight,
                    "destinations": summary
                },
                status=status.HTTP_200_OK)

        except Exception as e:
            # Comprehensive error logging
            logger.error(f"Error generating order report: {str(e)}",
                         extra={
                             'order_id': order_id,
                             'error_type': type(e).__name__,
                             'error_details': str(e)
                         }
                         )
            return Response({
                'error': 'Unable to generate order report',
                'details': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FeedbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id, *args, **kwargs):
        try:
            order = get_object_or_404(Order, id=order_id)
            rating = request.data.get("rating", 0)
            comments = request.data.get("comments")

            if not (rating and comments):
                return Response({"error": "Rating and comments are required."}, status=status.HTTP_400_BAD_REQUEST)

            Feedback.objects.create(order=order, rating=rating, comments=comments)

            return Response({"message": "Feedback submitted successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error submitting feedback: {str(e)}")
            return Response({"error": "Could not submit feedback."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id, *args, **kwargs):
        try:
            order = get_object_or_404(Order, id=order_id)
            reason = request.data.get("reason")

            if not reason:
                return Response({"error": "Reason for cancellation is required."}, status=status.HTTP_400_BAD_REQUEST)

            order.status = "Cancelled"
            order.cancellation_reason = reason
            order.save()

            return Response({"message": "Order cancelled successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            return Response({"error": "Could not cancel order."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
