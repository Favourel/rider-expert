import decimal
from django.utils import timezone
from decimal import Decimal
from accounts.models import Rider
from django.db import transaction
from django.db.models import Avg, Q

from django.shortcuts import get_object_or_404
from accounts.utils import (
    DistanceCalculator,
    generate_otp,
    send_customer_notification,
    send_riders_notification,
    str_to_bool,
)
from map_clients.map_clients import MapClientsManager, get_distance
from map_clients.supabase_query import SupabaseTransactions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from wallet.models import PendingWalletTransaction, WalletTransaction
from .models import DeclinedOrder, Order
from accounts.models import Rider
from .serializers import (
    OrderDetailUserSerializer,
    OrderSerializer,
    OrderDetailSerializer,
)
import logging


map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

logger = logging.getLogger(__name__)


def get_rider_available(SEARCH_RADIUS_KM, order_location):
    fields = ["rider_email", "current_lat", "current_long"]
    riders_location_data = supabase.get_supabase_riders(fields=fields)

    distance_calc = DistanceCalculator(order_location)
    riders_within_radius = distance_calc.destinations_within_radius(
        riders_location_data, SEARCH_RADIUS_KM
    )
    return riders_within_radius


def get_ride_average_cost(riders_within_radius, order_location, recipient_location):
    rider_emails = [rider["email"] for rider in riders_within_radius]

    # Query Rider model to get charge_per_km for riders within radius
    riders_within_radius_queryset = Rider.objects.filter(user__email__in=rider_emails)
    average_charge_per_km = riders_within_radius_queryset.aggregate(
        avg_charge=Avg("charge_per_km")
    )["avg_charge"]

    trip_distance = get_distance(order_location, recipient_location)

    # Convert trip_distance to Decimal
    trip_distance_decimal = Decimal(str(trip_distance))

    # Calculate the cost based on the average charge_per_km and trip_distance
    cost = round((average_charge_per_km * trip_distance_decimal), 2)

    return cost


class CreateOrderView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = OrderSerializer(data=request.data)

        recipient_lat = request.data.get("recipient_lat")
        recipient_long = request.data.get("recipient_long")

        pickup_lat = request.data.get("pickup_lat")
        pickup_long = request.data.get("pickup_long")

        order_location = f"{pickup_long},{pickup_lat}"
        recipient_location = f"{recipient_long},{recipient_lat}"

        if serializer.is_valid():
            serializer.validated_data["customer"] = request.user.customer

            riders_within_radius = get_rider_available(
                self.SEARCH_RADIUS_KM, order_location
            )

            if riders_within_radius:
                cost = get_ride_average_cost(
                    riders_within_radius, order_location, recipient_location
                )
                serializer.save()
                # Include cost in serializer data
                response_data = serializer.data
                response_data["cost"] = cost

                return Response(response_data, status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {"error": "No riders found within the search radius."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GetAvailableRidersView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5

    def validate_parameters(self, price_offer):
        """Validate input parameters."""
        try:
            price_offer = float(price_offer)
        except ValueError as e:
            logger.error(e)
            return False, f"Invalid or missing parameters, {e}"

        if not all(isinstance(param, (float, int)) for param in [price_offer]):
            return False, "Invalid or missing parameters"
        return True, ""

    def get(self, request, *args, **kwargs):
        price_offer = request.GET.get("price")
        order_id = request.GET.get("order_id")
        order = get_object_or_404(Order, id=int(order_id))
        item_weight = order.weight
        origin_lat = order.pickup_lat
        origin_long = order.pickup_long
        is_fragile = order.fragile

        customer = request.user.customer

        is_valid, validation_message = self.validate_parameters(price_offer)
        if not is_valid:
            return Response(
                {"status": "error", "message": validation_message}, status=400
            )

        origin = f"{origin_long},{origin_lat}"
        fields = ["rider_email", "current_lat", "current_long"]
        riders_location_data = supabase.get_supabase_riders(fields=fields)

        # Fetch all Rider objects that meet the conditions in a single query
        rider_queryset = Rider.objects.filter(
            user__email__in=[rider["email"] for rider in riders_location_data],
            fragile_item_allowed=is_fragile,
            min_capacity__lte=item_weight,
            max_capacity__gte=item_weight,
        )

        # Create a dictionary to map rider emails to rider objects
        rider_email_to_rider = {rider.user.email: rider for rider in rider_queryset}

        # Iterate through riders_location_data and filter the Rider objects
        riders = []
        for rider in riders_location_data:
            rider_email = rider["email"]
            if rider_email in rider_email_to_rider:
                rider_info = {
                    "email": rider_email,
                    "location": rider["location"],
                }
                riders.append(rider_info)

        if riders and origin:
            calculator = DistanceCalculator(origin)
            location_within_radius = calculator.destinations_within_radius(
                riders, self.SEARCH_RADIUS_KM
            )
            if not location_within_radius:
                send_customer_notification.delay(
                    customer=customer.user.email, message="No rider around you"
                )
            else:
                try:
                    results = self.get_matrix_results(origin, location_within_radius)

                except Exception as e:
                    logger.error(f"Error processing API request: {str(e)}")
                    map_clients_manager.switch_client()
                    results = self.get_matrix_results(origin, location_within_radius)
            send_riders_notification.delay(
                results,
                price=price_offer,
                request_coordinates={"long": origin_long, "lat": origin_lat},
                order_id=order_id,
            )
        order.status = "RiderSearch"
        order.save()
        order_data = OrderDetailUserSerializer(order).data
        return Response(
            {
                **order_data,
                "status": "success",
                "order_status": order.status,
                "message": "Notification sent successfully",
            }
        )

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, id=order_id)
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GetOrderDetailByUser(APIView):
    SEARCH_RADIUS_KM = 5
    permission_classes = [IsAuthenticated]

    def get(self, request, email, *args, **kwargs):
        print(email)
        user_type = request.GET.get("user_type")
        order = Order.objects.filter(
            Q(customer__user__email=email) | Q(rider__user__email=email)
        )
        if order:
            order = order.latest("created_at")
            extra_data = {}
            if user_type == "customer":
                order_location = f"{order.pickup_long},{order.pickup_lat}"
                recipient_location = f"{order.recipient_long},{order.recipient_lat}"
                available_riders = get_rider_available(
                    self.SEARCH_RADIUS_KM, order_location
                )
                cost = get_ride_average_cost(
                    available_riders, order_location, recipient_location
                )
                extra_data["cost"] = cost

            serializer = OrderDetailUserSerializer(order)
            return Response(
                {**serializer.data, **extra_data}, status=status.HTTP_200_OK
            )
        else:
            return Response({"message": "Order not found"}, status=status.HTTP_200_OK)


class AcceptOrDeclineOrderView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        order_id = request.data.get("order_id")
        price = request.data.get("price")
        accept = request.data.get("accept")
        reason = request.data.get("reason")

        # Get authenticated rider from request
        rider = request.user.rider_profile
        order = get_object_or_404(Order, id=order_id)

        if accept and reason is None:
            pickup_lat = order.pickup_lat
            pickup_long = order.pickup_long
            recipient_long = order.recipient_long
            recipient_lat = order.recipient_lat

            order_location = f"{pickup_long},{pickup_lat}"
            recipient_location = f"{recipient_long},{recipient_lat}"

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

            trip_distance = get_distance(order_location, recipient_location)

            # Calculate the cost of the ride based on the distance of the trip
            cost_of_ride = round((float(rider.charge_per_km) * trip_distance), 2)

            rider_info = {
                "rider_name": rider.user.get_full_name,
                "rider_email": rider.user.email,
                "vehicle_number": rider.vehicle_registration_number,
                "rating": rider.ratings if rider.ratings is not None else 0,
                "distance": distance,
                "duration": duration,
                "order_completed": rider.completed_orders,
                "price": price if price else cost_of_ride,
            }
            send_customer_notification.delay(
                customer=order.customer.user.email,
                message="Notifying riders close to you",
                rider_info=rider_info,
            )

            # Return a success message
            return Response(
                {"message": "Notification sent successfully"},
                status=status.HTTP_201_CREATED,
            )
        elif reason and not accept:
            rider.declined_requests += 1
            rider.save()
            # Create and save DeclinedOrder instance
            DeclinedOrder.objects.create(
                order=order,
                customer=None,
                rider=rider,
                decline_reason=reason,
            )

            # Return response for declined order
            return Response(
                {"message": "Order declined successfully"},
                status=status.HTTP_201_CREATED,
            )

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class AssignOrderToRiderView(APIView):
    """
    This view assigns an order to a rider.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """
        This method handles the POST request to assign an order to a rider.
        It assigns the rider to the order, updates the order status, and sends notifications to both the rider and the customer.
        """

        rider_email = request.data.get("rider_email")
        order_id = request.data.get("order_id")
        price = request.data.get("price")
        wallet = request.user.wallet

        if wallet.balance < decimal.Decimal(price):
            return Response(
                {"error": "Insufficient balance"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Get the order and rider objects
            order = get_object_or_404(Order, id=order_id)
            rider = get_object_or_404(Rider, user__email=rider_email)

            # Assign the rider to the order and update the order status
            order.rider = rider
            order.status = "WaitingForPickup"

            # Get the order location
            order_location = f"{order.pickup_long},{order.pickup_lat}"

            # Define conditions and fields for retrieving rider data from supabase
            conditions = [{"column": "rider_email", "value": rider_email}]
            fields = ["rider_email", "current_lat", "current_long"]

            # Retrieve rider data from supabase
            rider_data = supabase.get_supabase_riders(
                conditions=conditions, fields=fields
            )

            try:
                # Get distance and duration from the matrix results
                result = self.get_matrix_results(order_location, rider_data)
            except Exception as e:
                # Handle exception and retry
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                result = self.get_matrix_results(order_location, rider_data)

            # Extract distance and duration from the result
            distance = result[0]["distance"]
            duration = result[0]["duration"]

            order_info = {
                "id": order.id,
                "name": order.name,
                "weight": order.weight,
                "value": order.value,
                "quantity": order.quantity,
                "fragile": order.fragile,
                "recipient_name": order.recipient_name,
                "recipient_address": order.recipient_address,
            }

            # Send notification to the rider
            rider_message = (
                f"Order Accepted: Order is {distance} km and {duration} away"
            )

            # Generate order_completion code
            code = generate_otp(length=4)

            # Update the order price and save the order
            order.price = decimal.Decimal(price) * 100
            wallet.balance -= decimal.Decimal(price) * 100
            order.order_completion_code = code
            wallet.updated_at = timezone.now()
            wallet.save()
            order.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="debit",
                amount=price,
                transaction_status="pending",
                created_at=timezone.now(),
                paid_at=timezone.now(),
            )

            PendingWalletTransaction.objects.create(
                user=request.user, order=order, amount=price
            )

            customer_message = f"Order Assigned successfully: {rider.user.get_full_name} is {distance} km and {duration} away. Order code: {code}"

            # Serialize the updated order and attach distance and duration
            serializer = OrderSerializer(order)
            response_data = serializer.data
            response_data["distance"] = distance
            response_data["duration"] = duration

            send_riders_notification.delay(
                result,
                message=rider_message,
                order_id=order_id,
                price=price,
                order_info=response_data,
                request_coordinates={
                    "long": order.pickup_long,
                    "lat": order.pickup_lat,
                },
            )
            customer_message = f"Order Assigned successfully: {rider.user.get_full_name} is {distance} km and {duration} away"
            return Response(
                {
                    "message": customer_message,
                    **response_data,
                    "price": order.price,
                    "code": code,
                },
                status=status.HTTP_200_OK,
            )
        except (Rider.DoesNotExist, Order.DoesNotExist):
            # Handle if rider or order not found
            return Response("Rider or Order not found")

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class UpdateOrderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        order_id = request.data.get("order_id")
        order_status = request.data.get("status")
        order_code = request.data.get("order_code")

        if not order_id or not order_status:
            return Response(
                {"error": "Both order_id and status are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        if order_status not in valid_statuses:
            return Response(
                {"error": f"Invalid status: {order_status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order_status == "Delivered" and not order_code:
            return Response(
                {"error": "order_code is required for Delivered status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if the order exists
        order = get_object_or_404(Order, id=order_id)

        # Verify order code if required
        if order_status == "Delivered" and order.order_completion_code != order_code:
            return Response(
                {"error": "Invalid order code."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Update order status
        order.status = order_status
        order.save()

        send_customer_notification(
            customer=order.customer.user.email,
            message=f"Status update {order_status}",
            ride_status=order_status,
            by_pass_rider_info=True,
        )

        return Response(
            {
                "message": f"Order status updated to {order_status}.",
                "order_status": order_status,
            },
            status=status.HTTP_200_OK,
        )
