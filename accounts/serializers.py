from rest_framework import serializers
from .models import Customer, CustomUser, Rider
import logging

logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the CustomUser model. It includes custom validation for the password
    and email fields
    """

    password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = CustomUser
        fields = [
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "password",
            "confirm_password",
        ]

    def validate_password(self, value):
        # Password must be at least 8 characters long
        if len(value) < 8:
            raise serializers.ValidationError(
                "Password must be at least 8 characters long."
            )

        # Check for at least one uppercase character
        if not any(char.isupper() for char in value):
            raise serializers.ValidationError(
                "Password must contain at least one uppercase character."
            )

        # Check for at least one special character
        special_characters = "!@#$%^&*()-_=+[]{}|;:'\",.<>/?"
        if not any(char in special_characters for char in value):
            raise serializers.ValidationError(
                "Password must contain at least one special character."
            )

        # Check for at least one number
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError(
                "Password must contain at least one number."
            )
        return value

    def validate_email(self, value):
        if CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate(self, data):
        # Check if password and confirm_password match
        password = data.get("password")
        confirm_password = data.get("confirm_password")
        logger.debug({password, confirm_password})
        if password != confirm_password:
            raise serializers.ValidationError("Passwords do not match.")
        return data

    def create(self, validated_data):
        # Remove 'confirm_password' from the data before creating the user
        validated_data.pop("confirm_password", None)

        # Retrieve password directly from validated_data
        password = validated_data.get("password")

        # Ensure that password is not None before validating its length
        if password is None:
            raise serializers.ValidationError("Password cannot be empty.")

        self.validate_password(password)

        # Create the user without 'confirm_password'
        user = CustomUser.objects.create_user(**validated_data)

        # Set the password for the user
        user.set_password(password)
        user.save()

        return user


class CustomerSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Customer
        fields = ["user"]


class RiderSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Rider
        fields = (
            "user",
            "vehicle_type",
            "vehicle_registration_number",
            "min_capacity",
            "max_capacity",
            "fragile_item_allowed",
            "charge_per_km",
            "ratings",
        )
