from rest_framework import serializers
from .models import Order

class OrderSerializer(serializers.Serializer):
    quantity = serializers.IntegerField()
    pickup_location = serializers.CharField()
    delivery_location = serializers.CharField()
