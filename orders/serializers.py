from rest_framework import serializers
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    distance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    duration = serializers.CharField(max_length=20, read_only=True)
    rider = serializers.StringRelatedField()
    customer = serializers.StringRelatedField()

    class Meta:
        model = Order
        fields = [
            "id",
            "name",
            "pickup_lat",
            "pickup_long",
            "pickup_address",
            "recipient_name",
            "recipient_lat",
            "recipient_long",
            "recipient_address",
            "recipient_phone_number",
            "weight",
            "value",
            "fragile",
            "price",
            "cost",
            "distance",
            "duration",
            "status",
            "customer",
            "rider",
        ]

        read_only_fields = ["customer"]


class OrderDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        exclude = ["order_completion_code"]
