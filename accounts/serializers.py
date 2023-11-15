from datetime import timedelta
from django.utils import timezone
from django.urls import reverse
from django.core.mail import send_mail
from rest_framework import serializers
from smtplib import SMTPException
from .models import CustomUser, Customer
import secrets


class CustomerSerializer(serializers.ModelSerializer):
    """
    Serializer for the Customer model. It includes custom validation for the password
    and email fields, and a create method that generates a verification token, sends a
    verification email, and creates a new user.
    """

    password = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}
    )

    class Meta:
        model = Customer
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

    def create(self, validated_data):
        user_id = validated_data.pop("user_id")
        user = CustomUser.objects.get(id=user_id)
        customer = Customer.objects.create(user=user, **validated_data)
        return customer

    def create(self, validated_data):
        # Generate a random verification token
        token = secrets.token_urlsafe(32)

        # Set the token expiration time (e.g., 1 minutes)
        expiration_time = timezone.now() + timedelta(minutes=15)

        # Save the token and expiration time to the user instance
        validated_data["verification_token"] = token
        validated_data["verification_token_expires"] = expiration_time

        # Create the user instance
        user = super(CustomerSerializer, self).create(validated_data)

        # Send the verification email
        verification_url = reverse("verify-email") + f"?token={token}"
        try:
            send_mail(
                "Verify Your Email",
                f"Click the following link to verify your email: {verification_url}",
                "from@example.com",
                [user.email],
                fail_silently=False,
            )
        except SMTPException:
            raise serializers.ValidationError("Email could not be sent.")

        return user
