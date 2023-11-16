from django.db import DatabaseError
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import CustomerSerializer
from .models import UserVerification
from .utils import send_verification_email
import logging

logger = logging.getLogger(__name__)


class RegisterCustomerView(APIView):
    """
    API view to handle user registration.
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests. Validate the request data using the CustomerSerializer,
        create a new user if the data is valid, and return a response with the user data
        or validation errors.
        """
        logger.debug(f"Request_data: {request.data}")
        serializer = CustomerSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                if user:
                    # Automatically send verification email upon successful registration
                    send_verification_email(user)
                    return Response(
                        {
                            "data": serializer.data,
                            "message": "Thank you for registering",
                        },
                        status=status.HTTP_201_CREATED,
                    )
            except DatabaseError:
                return Response(
                    {"detail": "Database error."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyEmailView(APIView):
    """
    API view to handle email verification.
    """

    def post(self, request, *args, **kwargs):
        """
        Handle GET requests. Validate the verification token, mark the user's email as
        verified if the token is valid, and return a response with a success message or
        error message.
        """
        otp_token = request.data.get("otp_token")

        if not otp_token:
            return Response(
                {"detail": "OTP token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_verification = UserVerification.objects.get(
                email_otp=otp_token, email_expiration_time__gt=timezone.now()
            )
        except UserVerification.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired OTP token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user_verification.is_verified():
            return Response(
                {"detail": "Email is already verified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = user_verification.user
        user.is_verified = True
        user.save()

        # Expire the OTP after successful verification
        user_verification.email_otp = None
        user_verification.email_expiration_time = None
        user_verification.save()

        return Response(
            {"detail": "Email verified successfully"}, status=status.HTTP_200_OK
        )


class ResendTokenView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get(
            "email"
        )  # Assuming the email is sent in the request data

        if not email:
            return Response(
                {"detail": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_verification = UserVerification.objects.get(user__email=email)
        except UserVerification.DoesNotExist:
            return Response(
                {"detail": "User verification record not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user_verification.is_email_verified():
            return Response(
                {"detail": "Email is already verified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user_verification.email_expiration_time > timezone.now():
            # The previous OTP has not expired, no need to resend
            return Response(
                {"detail": "Previous OTP has not expired"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Send the new OTP via email
        send_verification_email(user_verification.user)

        return Response(
            {"detail": "New OTP has been sent to your email"}, status=status.HTTP_200_OK
        )
