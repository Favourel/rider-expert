from rest_framework import serializers
from .models import Order


class OrderSerializer(serializers.ModelSerializer):
    cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "pickup_lat",
            "pickup_long",
            "pickup_address",
            "recipients_name",
            "recipient_lat",
            "recipient_long",
            "recipient_address",
            "recipient_phone_number",
            "parcel_weight",
            "parcel_value",
            "fragile",
            "cost"
        ]

        read_only_fields = ["customer"]


class OrderDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        exclude = ["order_completion_code"]
