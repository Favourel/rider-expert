import decimal

from django.db import transaction
from django.db.models import Q, Avg, Sum, Count
from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.generics import GenericAPIView
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
    """
    API view for riders to accept or decline their assigned sub-order in a bulk order.
    """
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        try:
            # Parse and validate input
            order_id = request.data.get("order_id")
            price = request.data.get("price")
            accept = request.data.get("accept", False)
            reason = request.data.get("reason", "")

            if not order_id:
                return Response(
                    {"error": "Order ID is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get authenticated rider and assignment
            rider = request.user.rider_profile
            order_assignment = get_object_or_404(
                OrderRiderAssignment,
                order_id=order_id,
                rider=rider
            )

            # Handle acceptance
            if accept and not reason:
                return self.handle_assignment_acceptance(order_assignment)

            # Handle rejection
            if not accept and reason:
                return self.handle_assignment_rejection(order_assignment, rider, reason)

            # Invalid request
            return Response(
                {"error": "Provide either accept=True or a reason for rejection."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.error(f"Error in AcceptOrDeclineOrderAssignmentView: {str(e)}")
            return Response(
                {"error": "An unexpected error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def handle_assignment_acceptance(self, order_assignment):
        """
        Handles the acceptance of an order assignment by a rider.

        Args:
            order_assignment (OrderRiderAssignment): The assignment being accepted.

        Returns:
            Response: Success message with updated order and rider details.
        """
        try:
            # Get related order and rider details
            order = order_assignment.order
            rider = order_assignment.rider

            # Prepare coordinates for distance and duration calculation
            pickup_lat = order.pickup_lat
            pickup_long = order.pickup_long
            recipient_lat = order.recipient_lat
            recipient_long = order.recipient_long

            order_location = f"{pickup_long},{pickup_lat}"
            recipient_location = f"{recipient_long},{recipient_lat}"

            # Fetch rider data from Supabase
            conditions = [{"column": "rider_email", "value": rider.user.email}]
            fields = ["rider_email", "current_lat", "current_long"]
            rider_data = supabase.get_supabase_riders(conditions=conditions, fields=fields)

            # Calculate distance and duration
            try:
                result = self.get_matrix_results(order_location, rider_data)
            except Exception as e:
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                result = self.get_matrix_results(order_location, rider_data)

            distance = result[0]["distance"]
            duration = result[0]["duration"]

            # Calculate trip distance and cost
            trip_distance = get_distance(order_location, recipient_location)
            cost_of_ride = round(float(rider.charge_per_km) * trip_distance, 2)

            # Update the order assignment and parent order
            order_assignment.status = "Accepted"
            order_assignment.distance = distance
            order_assignment.duration = duration
            order_assignment.assigned_weight = order.total_weight  # Example: Can be adjusted based on bulk logic
            order_assignment.save()

            # Update parent order status based on all assignments
            assignments = order.orderriderassignment_set.all()
            if all(assignment.status == "Accepted" for assignment in assignments):
                order.status = "Assigned"
            elif any(assignment.status == "Accepted" for assignment in assignments):
                order.status = "PartiallyAssigned"
            order.save()

            # Notify customer
            rider_info = {
                "rider_name": rider.user.get_full_name(),
                "rider_email": rider.user.email,
                "vehicle_number": rider.vehicle_registration_number,
                "rating": rider.ratings if rider.ratings is not None else 0,
                "distance": f"{distance:.2f} km",
                "duration": f"{duration} minutes",
                "order_completed": rider.completed_orders,
                "price": f"{cost_of_ride:.2f}",
            }
            send_customer_notification.delay(
                customer=order.customer.user.email,
                message="Your order has been accepted by the rider!",
                rider_info=rider_info,
            )

            return Response(
                {"message": "Assignment accepted successfully.", "rider_info": rider_info},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error accepting assignment {order_assignment.id}: {str(e)}")
            raise

    def handle_assignment_rejection(self, order_assignment, rider, reason):
        """
        Handles the rejection of an order assignment by a rider.

        Args:
            order_assignment (OrderRiderAssignment): The assignment being rejected.
            rider (Rider): The rider rejecting the assignment.
            reason (str): The reason for rejection.

        Returns:
            Response: Success message indicating rejection.
        """
        try:
            order_assignment.status = "Declined"
            order_assignment.save()

            # Update rider statistics
            rider.declined_requests += 1
            rider.save()

            # Log declined order
            DeclinedOrder.objects.create(
                order=order_assignment.order,
                customer=None,
                rider=rider,
                decline_reason=reason,
            )

            # Find replacement rider
            self.find_replacement_rider(order_assignment)

            return Response(
                {"message": "Assignment declined successfully."},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error rejecting assignment {order_assignment.id}: {str(e)}")
            raise

    def find_replacement_rider(self, declined_assignment):
        """
        Finds a replacement rider for a declined order assignment.

        Args:
            declined_assignment (OrderRiderAssignment): The declined assignment.

        Returns:
            Rider or None: A replacement rider if found.
        """
        try:
            order = declined_assignment.order
            declined_weight = declined_assignment.package_weight
            pickup_location = f"{order.pickup_long},{order.pickup_lat}"

            # Find suitable alternative riders
            alternative_riders = Rider.objects.filter(
                max_capacity__gte=declined_weight,
                min_capacity__lte=declined_weight,
                fragile_item_allowed=order.fragile
            ).exclude(
                id__in=[declined_assignment.rider.id] + list(order.riders.values_list("id", flat=True))
            )

            # Fetch rider locations and prioritize by proximity
            fields = ["rider_email", "current_lat", "current_long"]
            riders_location_data = supabase.get_supabase_riders(fields=fields)
            distance_calculator = DistanceCalculator(pickup_location)

            nearby_suitable_riders = [
                rider for rider in riders_location_data
                if rider["email"] in alternative_riders.values_list("user__email", flat=True)
            ]

            nearby_suitable_riders.sort(
                key=lambda r: distance_calculator.calculate_distance(
                    f"{r['current_long']},{r['current_lat']}"
                )
            )

            # Assign closest rider
            if nearby_suitable_riders:
                closest_rider_email = nearby_suitable_riders[0]["email"]
                replacement_rider = Rider.objects.get(user__email=closest_rider_email)

                OrderRiderAssignment.objects.create(
                    order=order,
                    rider=replacement_rider,
                    assigned_weight=declined_weight,
                    status="Pending",
                )

                send_riders_notification.delay(
                    riders=[replacement_rider],
                    order_id=order.id,
                    assigned_weight=declined_weight,
                    replacement_notification=True,
                )

                logger.info(
                    f"Replacement rider {replacement_rider.user.email} assigned for Order {order.id}"
                )
                return replacement_rider

        except Exception as e:
            logger.error(
                f"Error finding replacement rider for Order {declined_assignment.order.id}: {str(e)}"
            )
            self.handle_order_assignment_errors(
                declined_assignment.order,
                "partial_assignment_failure"
            )
            return None


        # except Exception as e:
        #     # Comprehensive error handling for replacement process
        #     logger.error(
        #         f"Error finding replacement rider for Order {order.id}",
        #         extra={
        #             'order_id': order.id,
        #             'error_type': type(e).__name__,
        #             'error_details': str(e)
        #         }
        #     )
        #
        #     # Escalate if no replacement found
        #     self.handle_order_assignment_errors(
        #         order,
        #         'partial_assignment_failure'
        #     )
        #
        #     return None

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


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
        try:
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

        except Exception as err:
            return Response({"error": str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RealTimeOrderTrackingView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5

    def get(self, request, order_id, *args, **kwargs):
        try:
            order = get_object_or_404(Order, id=order_id)
            riders = order.assignments.all()  # Fetch all associated riders

            riders_data = []
            for rider in riders:
                # Fetch assignment for the current rider and order
                assignments = OrderRiderAssignment.objects.filter(order=order, rider=rider.rider, customer=request.user.customer)
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
                        "email": rider.rider.email,
                        "name": rider.rider.get_full_name(),
                        "assignment_status": assignment.status,
                        "rider_status": rider.rider.status,
                        "rider_location": {
                            "lat": rider.rider.current_lat,
                            "long": rider.rider.current_long
                        },
                        "distance_to_destination": f"{distance} km",
                        "eta": f"{duration} minutes",
                    })

            # Serialize order details
            serializer = OrderDetailSerializer(order)
            return Response({**serializer.data, "riders": riders_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error in tracking order {order_id}: {str(e)}")
            return Response({"error": "Could not fetch tracking details.", "details": f"{str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_additional_information(self, order, rider):
        order_location = f"{order.pickup_long},{order.pickup_lat}"
        conditions = [{"column": "rider_email", "value": rider.rider.email}]
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
            assignments = OrderRiderAssignment.objects.filter(order=bulk_order, customer=request.user.customer)

            summary = [
                {
                    "id": assignment.id,
                    "destination": {
                        "lat": assignment.recipient_lat,
                        "long": assignment.recipient_long,
                    },
                    "status": assignment.status,
                    'assigned_weight': assignment.package_weight,
                    'rider_capacity': {
                        'min_capacity': assignment.rider.min_capacity,
                        'max_capacity': assignment.rider.max_capacity
                    },
                    "rider": assignment.rider.user.get_full_name if assignment.rider else None
                }
                for assignment in assignments
            ]

            # Logging the report generation
            logger.info(f"Order {order_id} report generated",
                        extra={
                            'order_id': order_id,
                            'total_riders': len([assignment.rider for assignment in assignments]),
                            # 'fulfilled_percentage': (bulk_order.fulfilled_weight / bulk_order.total_weight) * 100
                        })

            return Response(
                {
                    "bulk_order_id": bulk_order.id,
                    "total_weight": bulk_order.total_weight,
                    # 'fulfilled_weight': bulk_order.fulfilled_weight,
                    # "remaining_weight": bulk_order.remaining_weight,
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

            if order.status != "Delivered":
                return Response({"error": "Order has to be delivered before you can provide feedback."}, status=status.HTTP_400_BAD_REQUEST)

            Feedback.objects.create(customer=request.user.customer, order=order, rating=rating, comments=comments)

            return Response({"message": "Feedback submitted successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error submitting feedback: {str(e)}")
            return Response({"error": f"Could not submit feedback.: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id, *args, **kwargs):
        try:
            order = get_object_or_404(Order, id=order_id)
            # Ensure the logged-in user is the customer associated with the order
            if order.customer != request.user.customer:
                return Response(
                    {"error": "You do not have permission to cancel this order."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            reason = request.data.get("reason")

            if not reason:
                return Response({"error": "Reason for cancellation is required."}, status=status.HTTP_400_BAD_REQUEST)

            order.status = "Cancelled"
            order.cancellation_reason = reason
            order.save()

            return Response({"message": "Order cancelled successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            return Response({"error": f"Could not cancel order. Reason: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
