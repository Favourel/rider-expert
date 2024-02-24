from accounts.models import Rider
from accounts.serializers import RiderSerializer
from django.db import transaction
from django.shortcuts import get_object_or_404
from map_clients.map_clients import MapClientsManager
from map_clients.supabase_query import SupabaseTransactions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Order
from .serializers import OrderSerializer, OrderDetailSerializer
import logging

map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

logger = logging.getLogger(__name__)


class CreateOrder(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = OrderSerializer(data=request.data)
        if serializer.is_valid():
            serializer.validated_data["customer"] = request.user.customer
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
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
        order = get_object_or_404(Order, id=order_id)

        rider = get_object_or_404(Rider, user__email=rider_email)
        order_location = f"{order.pickup_long:.6f},{order.pickup_lat:.6f}"

        conditions = [{"column": "rider_email", "value": rider_email}]
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

        # Calculate the cost of the ride based on the distance of the trip
        cost_of_ride = round((rider.charge_per_km * distance / 1000), 2)

        serializer = RiderSerializer(rider)

        # Return the rider's information
        return Response(
            {
                "rider": serializer.data,
                "cost_of_ride": cost_of_ride,
                "distance": distance,
                "duration": duration,
            },
            status=status.HTTP_200_OK,
        )

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results
