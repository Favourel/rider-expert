from rest_framework import serializers
from .models import Customer, CustomUser
import logging

logger = logging.getLogger(__name__)


class CustomUserSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}
    )

    class Meta:
        model = CustomUser
        fields = "__all__"

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
        if Customer.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate(self, data):
        # Check if password and confirm_password match
        if data.get("password") != data.pop("confirm_password"):
            raise serializers.ValidationError("Passwords do not match.")
        return data


class CustomerSerializer(serializers.ModelSerializer):
    """
    Serializer for the Customer model. It includes custom validation for the password
    and email fields, and a create method that generates a verification token, sends a
    verification email, and creates a new user.
    """

    user_id = CustomUserSerializer()

    class Meta:
        model = Customer
        fields = "__all__"

    def create(self, validated_data):
        logger.debug(f"Validated_data: {validated_data}")
        user_data = validated_data.get("user_id")
        user_serializer = CustomUserSerializer(data=user_data)
        user_serializer.is_valid()
        user = user_serializer.save()
        customer = Customer.objects.create(user_id=user, **validated_data)
        return customer
