from accounts.serializers import CustomerSerializer, RiderDetailSerializer
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
            "is_bulk",  # Include the is_bulk field
            "weight",  # For bulk orders
            "destinations",  # To handle nested data for bulk orders
        ]

        read_only_fields = ["customer"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically adjust required fields based on is_bulk
        is_bulk = self.initial_data.get("is_bulk", False)
        if is_bulk:
            # Remove single order specific fields for bulk orders
            self.fields.pop("recipient_name", None)
            self.fields.pop("recipient_address", None)
            self.fields.pop("recipient_phone_number", None)
            self.fields.pop("weight", None)
            self.fields.pop("value", None)
        else:
            # Remove bulk order specific fields for single orders
            self.fields.pop("destinations", None)
            # self.fields.pop("weight", None)

    def validate(self, attrs):
        is_bulk = self.initial_data.get("is_bulk", False)
        if is_bulk:  # Validate for bulk orders
            if not self.initial_data.get("weight"):
                raise serializers.ValidationError({"weight": "This field is required for bulk orders."})
            if not self.initial_data.get("destinations"):
                raise serializers.ValidationError({"destinations": "At least one destination is required for bulk orders."})

            # Validate destinations format
            for destination in self.initial_data["destinations"]:
                required_fields = ["lat", "long", "recipient_name", "recipient_address", "recipient_phone_number"]
                missing_fields = [field for field in required_fields if field not in destination]
                if missing_fields:
                    raise serializers.ValidationError(
                        {"destinations": f"Each destination must include {', '.join(required_fields)}."}
                    )

        else:  # Validate for single orders
            required_fields = ["recipient_name", "recipient_address", "recipient_phone_number", "weight", "value"]
            missing_fields = [field for field in required_fields if not attrs.get(field)]
            if missing_fields:
                raise serializers.ValidationError(
                    {field: "This field is required." for field in missing_fields}
                )
        return attrs


class OrderDetailSerializer(serializers.ModelSerializer):
    customer = CustomerSerializer(read_only=True)
    rider = RiderDetailSerializer(read_only=True)

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
            "status",
            "customer",
            "rider",
            "distance",
            "duration",
        ]


class OrderDetailUserSerializer(serializers.ModelSerializer):
    cost = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    customer = CustomerSerializer(read_only=True)
    rider = RiderDetailSerializer(read_only=True)

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
            "status",
            "customer",
            "rider",
            "order_completion_code",
            "distance",
            "duration",
        ]
