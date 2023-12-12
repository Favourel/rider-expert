from django.shortcuts import render
from rest_framework.views import APIView
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated

from .models import Order, Rider

class AssignOrderToRiderAPIView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, order_id, rider_id):

        try:
            order = Order.objects.get(pk=order_id)
            rider = Rider.objects.get(pk=rider_id)
                

            # Assign the rider to the order
            order.rider = rider
            # Update the order status
            order.status = 'Waiting for pickup'
            order.save()

            return HttpResponse("Order assigned to rider successfully")
        except (Rider.DoesNotExist, Order.DoesNotExist):
            return HttpResponse("Rider or Order not found")