from django.utils import timezone
from decimal import Decimal
from accounts.models import Rider
from django.db import transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404
from accounts.utils import DistanceCalculator, str_to_bool
from map_clients.map_clients import MapClientsManager, get_distance
from map_clients.supabase_query import SupabaseTransactions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from wallet.models import WalletTransaction
from .models import DeclinedOrder, Order
from accounts.models import Rider
from .serializers import OrderSerializer, OrderDetailSerializer
import logging


map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

logger = logging.getLogger(__name__)


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

            fields = ["rider_email", "current_lat", "current_long"]
            riders_location_data = supabase.get_supabase_riders(fields=fields)

            distance_calc = DistanceCalculator(order_location)
            riders_within_radius = distance_calc.destinations_within_radius(
                riders_location_data, self.SEARCH_RADIUS_KM
            )

            if riders_within_radius:
                rider_emails = [rider["email"] for rider in riders_within_radius]

                # Query Rider model to get charge_per_km for riders within radius
                riders_within_radius_queryset = Rider.objects.filter(
                    user__email__in=rider_emails
                )
                average_charge_per_km = riders_within_radius_queryset.aggregate(
                    avg_charge=Avg("charge_per_km")
                )["avg_charge"]

                trip_distance = get_distance(order_location, recipient_location)

                # Convert trip_distance to Decimal
                trip_distance_decimal = Decimal(str(trip_distance))

                # Calculate the cost based on the average charge_per_km and trip_distance
                cost = round((average_charge_per_km * trip_distance_decimal), 2)

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

    def validate_parameters(
        self, origin_lat, origin_long, item_weight, is_fragile, price_offer, order_id
    ):
        """Validate input parameters."""
        try:
            origin_lat = float(origin_lat)
            origin_long = float(origin_long)
            item_weight = float(item_weight)
            price_offer = float(price_offer)
            is_fragile = str_to_bool(is_fragile)
            order_id = int(order_id)
        except ValueError as e:
            logger.error(e)
            return False, f"Invalid or missing parameters, {e}"

        if not all(
            isinstance(param, (float, int))
            for param in [origin_lat, origin_long, item_weight, price_offer, order_id]
        ) or not isinstance(is_fragile, bool):
            return False, "Invalid or missing parameters"
        return True, ""

    def get(self, request, *args, **kwargs):
        origin_long = float(request.GET.get("origin_long"))
        origin_lat = float(request.GET.get("origin_lat"))
        item_weight = request.GET.get("item_weight")
        is_fragile = request.GET.get("is_fragile")
        price_offer = request.GET.get("price")
        order_id = request.GET.get("order_id")

        customer = request.user.customer

        is_valid, validation_message = self.validate_parameters(
            origin_lat, origin_long, item_weight, is_fragile, price_offer, order_id
        )
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
                supabase.send_customer_notification(
                    customer=customer.user.email, message="No rider around you"
                )
            else:
                try:
                    results = self.get_matrix_results(origin, location_within_radius)

                except Exception as e:
                    logger.error(f"Error processing API request: {str(e)}")
                    map_clients_manager.switch_client()
                    results = self.get_matrix_results(origin, location_within_radius)

            supabase.send_riders_notification(
                results,
                price=price_offer,
                request_coordinates={"long": origin_long, "lat": origin_lat},
                order_id=order_id,
            )

        return Response(
            {"status": "success", "message": "Notification sent successfully"}
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
                "vehicle_number": rider.vehicle_registration_number,
                "rating": rider.ratings if rider.ratings is not None else 0,
                "distance": distance,
                "duration": duration,
                "order_completed": rider.completed_orders,
                "price": price if price else cost_of_ride,
            }
            supabase.send_customer_notification(
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

        if wallet.balance < price:
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
            order.status = "Waiting for pickup"

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

            # Serialize the updated order and attach distance and duration
            serializer = OrderSerializer(order)
            response_data = serializer.data
            response_data["distance"] = distance
            response_data["duration"] = duration

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
            supabase.send_riders_notification(
                result, message=rider_message, order_info=response_data
            )

            # Update the order price and save the order
            order.price = price
            wallet.balance -= price
            wallet.updated_at = timezone.now()
            wallet.save()
            order.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="Debit",
                amount=price,
                created_at=timezone.now(),
            )

            customer_message = f"Order Assigned successfully: {rider.user.get_full_name} is {distance} km and {duration} away"

            return Response({"message": customer_message}, status=status.HTTP_200_OK)
        except (Rider.DoesNotExist, Order.DoesNotExist):
            # Handle if rider or order not found
            return Response("Rider or Order not found")

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results
