from accounts.models import Rider
from accounts.serializers import RiderSerializer
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Order
from .serializers import OrderSerializer, OrderDetailSerializer
from django.shortcuts import get_object_or_404


class OrderCreateView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = OrderSerializer(data=request.data)

        if serializer.is_valid():
            quantity = serializer.validated_data['quantity']
            pickup_location = serializer.validated_data['pickup_location']
            delivery_location = serializer.validated_data['delivery_location']

            order = Order.objects.create(
                quantity=quantity,
                pickup_location=pickup_location,
                delivery_location=delivery_location,
            )

            return Response({'detail': 'Order created successfully'}, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrderDetailView(APIView):
    def get(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, id=order_id)
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AcceptOrderView(APIView):
    def post(self, request, *args, **kwargs):
        # Get the rider's user ID from the request data
        rider_user_id = request.data.get('rider_user_id')

        # Get the rider object using the user ID
        rider = get_object_or_404(Rider, user__id=rider_user_id)

        # Check if the rider has accepted the order
        if request.data.get('accept_order'):
            # Calculate the cost of the ride based on the distance of the trip
            distance = request.data.get('distance')
            cost_of_ride = rider.charge_per_mile * distance

            # Serialize the rider object
            serializer = RiderSerializer(rider)

            # Return the rider's information
            return Response({
                'rider_user_info': serializer.data['user'],
                'vehicle_number': rider.vehicle_registration_number,
                'vehicle_type': rider.vehicle_type,
                'ratings': rider.ratings,
                'cost_of_ride': cost_of_ride
            })
        else:
            # If the rider declines the order, return an empty response
            return Response({})
