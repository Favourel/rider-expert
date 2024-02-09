from django.utils import timezone
from django.core.mail import send_mail
from smtplib import SMTPException
from rest_framework import serializers
import pyotp
from django.conf import settings
from .models import UserVerification
from math import radians, sin, cos, sqrt, atan2


class DistanceCalculator:
    def __init__(self, origin):
        self.origin = origin

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate the distance between two points on the Earth's surface
        using the Haversine formula.

        Parameters:
        lat1, lon1: Latitude and longitude of point 1 (in degrees).
        lat2, lon2: Latitude and longitude of point 2 (in degrees).

        Returns:
        Distance between the two points in kilometers.
        """
        # Convert latitude and longitude from degrees to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = 6371 * c  # Earth radius in kilometers
        return distance

    def destinations_within_radius(self, destinations, radius):
        """
        Find destinations within a specified radius of the origin.

        Parameters:
        destinations: List of tuples, each containing latitude and longitude of a destination.
        radius: Radius in kilometers.

        Returns:
        List of destinations within the specified radius of the origin.
        """
        within_radius = []
        for destination in destinations:
            distance = self.haversine_distance(
                self.origin[0], self.origin[1], destination[0], destination[1]
            )
            if distance <= radius:
                within_radius.append((distance, destination))
        return within_radius


def generate_otp():
    # Generate a time-based OTP using PyOTP
    totp = pyotp.TOTP(pyotp.random_base32())
    otp_value = totp.now()
    return otp_value


def send_verification_email(user, purpose):
    otp_code = generate_otp()
    email = user.email
    current_site = "myAuth.com"
    from_email = settings.DEFAULT_FROM_EMAIL

    if purpose == "registration":
        subject = "One time passcode for Email verification"
        email_body = "Hi {} thanks for signing up on {} \nplease verify your email with the one time code {}".format(
            user.first_name, current_site, otp_code
        )
    elif purpose == "forgot_password":
        subject = "Reset your password"
        email_body = "Hi {} you requested a password reset on {} \nplease reset your password with the one-time code {}".format(
            user.first_name, current_site, otp_code
        )

    try:
        send_mail(subject, email_body, from_email, [email], fail_silently=False)
    except SMTPException:
        raise serializers.ValidationError("Email could not be sent.")

    # Save the OTP in the OTP model
    otp_instance, created = UserVerification.objects.get_or_create(user=user)
    otp_instance.otp = otp_code
    otp_instance.created_at = timezone.now()
    otp_instance.otp_expiration_time = timezone.now() + timezone.timedelta(minutes=30)
    otp_instance.save()


def str_to_bool(s):
    return s.lower() in ["true", "1", "yes", "on"]


def validate_password(value):
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
        raise serializers.ValidationError("Password must contain at least one number.")
    return value
