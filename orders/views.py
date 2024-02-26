from decimal import Decimal
from accounts.models import Rider
from accounts.serializers import RiderSerializer
from django.db import transaction
from django.db.models import Avg
from django.shortcuts import get_object_or_404
from accounts.utils import DistanceCalculator
from map_clients.map_clients import MapClientsManager
from map_clients.supabase_query import SupabaseTransactions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Order
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

        order_location = f"{pickup_long:.6f},{pickup_lat:.6f}"

        if serializer.is_valid():
            serializer.validated_data["customer"] = request.user.customer
            serializer.save()

            distance_calc = DistanceCalculator(order_location)

            trip_distance = distance_calc.haversine_distance(
                recipient_lat, recipient_long, pickup_lat, pickup_long
            )

            fields = ["rider_email", "current_lat", "current_long"]
            riders_location_data = supabase.get_supabase_riders(fields=fields)
            riders_within_radius = distance_calc.destinations_within_radius(
                riders_location_data, self.SEARCH_RADIUS_KM
            )

            rider_emails = [rider["email"] for rider in riders_within_radius]

            # Query Rider model to get charge_per_km for riders within radius
            riders_within_radius_queryset = Rider.objects.filter(
                user__email__in=rider_emails
            )
            average_charge_per_km = riders_within_radius_queryset.aggregate(
                avg_charge=Avg("charge_per_km")
            )["avg_charge"]

            # Convert trip_distance to Decimal
            trip_distance_decimal = Decimal(str(trip_distance))

            # Calculate the cost based on the average charge_per_km and trip_distance
            cost = round((average_charge_per_km * trip_distance_decimal), 2)

            # Include cost in serializer data
            response_data = serializer.data
            response_data["cost"] = cost

            return Response(response_data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, id=order_id)
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AcceptOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        rider_email = request.data.get("rider_email")
        order_id = request.data.get("order_id")
        price = request.data.get("price")

        order = get_object_or_404(Order, id=order_id)
        rider = get_object_or_404(Rider, user__email=rider_email)

        pickup_lat = order.pickup_lat
        pickup_long = order.pickup_long
        recipient_long = order.recipient_long
        recipient_lat = order.recipient_lat

        order_location = f"{pickup_long:.6f},{pickup_lat:.6f}"
        recipient_location = f"{recipient_long:.6f},{recipient_lat:.6f}"

        conditions = [{"column": "rider_email", "value": rider_email}]
        fields = ["rider_email", "current_lat", "current_long"]

        rider_data = supabase.get_supabase_riders(conditions=conditions, fields=fields)

        try:
            result = self.get_matrix_results(order_location, rider_data)
        except Exception as e:
            logger.error(f"Error processing API request: {str(e)}")
            map_clients_manager.switch_client()
            result = self.get_matrix_results(order_location, rider_data)

        distance = result[0]["distance"]
        duration = result[0]["duration"]

        distance_calc = DistanceCalculator(recipient_location)
        trip_distance = distance_calc.haversine_distance(
            recipient_lat, recipient_long, pickup_lat, pickup_long
        )

        # Calculate the cost of the ride based on the distance of the trip
        cost_of_ride = round((float(rider.charge_per_km) * trip_distance), 2)

        rider_price = price if price else cost_of_ride

        message = f"{rider.user.get_full_name} has accepted your order at a price of {rider_price}. he is {distance} km and {duration} away"

        order.rider = rider
        order.status = "accepted"
        order.save()

        supabase.send_customer_notification(
            customer=order.customer.user.email, message=message
        )

        # Return a success message
        return Response({"message": "Notification sent successfully"},status=status.HTTP_201_CREATED)

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

            # Send notification to the rider
            rider_message = (
                f"Order Accepted: Order is {distance} km and {duration} away"
            )
            supabase.send_riders_notification(result, message=rider_message)

            # Send notification to the customer
            customer = order.customer.user.email
            customer_message = (
                f"Order Accepted: Rider is {distance} km and {duration} away"
            )
            supabase.send_customer_notification(customer, customer_message)

            # Update the order price and save the order
            order.price = price
            order.save()

            # Serialize the updated order and attach distance and duration
            serializer = OrderSerializer(order)
            response_data = serializer.data
            response_data["distance"] = distance
            response_data["duration"] = duration

            return Response(response_data, status=status.HTTP_200_OK)
        except (Rider.DoesNotExist, Order.DoesNotExist):
            # Handle if rider or order not found
            return Response("Rider or Order not found")

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results
