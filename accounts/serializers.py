# from accounts.utils import validate_password
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from .models import *
import logging

logger = logging.getLogger(__name__)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = (
            "email",
            "first_name",
            "last_name",
            "phone_number",
        )


class CustomerSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    # User Related Fields
    email = serializers.EmailField(
        write_only=True, validators=[UniqueValidator(queryset=CustomUser.objects.all())]
    )
    first_name = serializers.CharField(write_only=True, required=True)
    last_name = serializers.CharField(write_only=True, required=True)
    phone_number = serializers.CharField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Customer
        fields = [
            "user",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "password",
            "confirm_password",
        ]

    def validate(self, data):
        password = data.get("password")
        confirm_password = data.pop("confirm_password")
        if password != confirm_password:
            raise serializers.ValidationError("Passwords do not match.")
        try:
            validate_password(value=password)
        except serializers.ValidationError as e:
            raise serializers.ValidationError(e)
        return data

    def create(self, validated_data):
        user = CustomUser.objects.create_user(**validated_data)
        customer = Customer.objects.create(user=user)

        return customer


class RiderSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    # User Related Fields
    email = serializers.EmailField(
        write_only=True, validators=[UniqueValidator(queryset=CustomUser.objects.all())]
    )
    first_name = serializers.CharField(write_only=True, required=True)
    last_name = serializers.CharField(write_only=True, required=True)
    phone_number = serializers.CharField(write_only=True, required=True)
    password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    # Rider Related Fields
    vehicle_registration_number = serializers.CharField(
        max_length=20, validators=[UniqueValidator(queryset=Rider.objects.all())]
    )
    min_capacity = serializers.IntegerField(required=False, allow_null=True)
    max_capacity = serializers.IntegerField(required=False, allow_null=True)
    fragile_item_allowed = serializers.BooleanField(default=True)
    charge_per_mile = serializers.DecimalField(
        max_digits=6, decimal_places=2, required=False, allow_null=True
    )

    class Meta:
        model = Rider
        fields = (
            "user",
            "vehicle_type",
            "vehicle_registration_number",
            "min_capacity",
            "max_capacity",
            "fragile_item_allowed",
            "charge_per_mile",
        )
