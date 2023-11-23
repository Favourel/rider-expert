from django.db import transaction, IntegrityError
from django.contrib.auth import authenticate
from django.utils import timezone
from .tokens import create_jwt_pair_for_user
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.serializers import ValidationError
from .serializers import *
from .models import *
from .utils import send_verification_email

import logging

logger = logging.getLogger(__name__)


class BaseUserRegistrationView(APIView):
    user_model = None
    serializer_class = None

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        logger.debug(f"Request_data: {request.data}")
        user_data = request.data

        # Validate UserSerializer first
        user_serializer = UserSerializer(data=user_data)

        if user_serializer.is_valid():
            # Access validated data after validation
            user_data = user_serializer.validated_data

            if user_data:
                try:
                    with transaction.atomic():
                        user = user_serializer.save()
                        user_obj = self.user_model.objects.create(user=user)
                        user_obj_serializer = self.serializer_class(user_obj).data

                        if user_obj_serializer:
                            # Send welcome email or perform any additional actions
                            send_verification_email(user)

                            return Response(
                                {
                                    "data": user_obj_serializer,
                                    "message": f"{self.user_model.__name__} registration successful",
                                },
                                status=status.HTTP_201_CREATED,
                            )
                        else:
                            raise ValidationError(detail=user_obj_serializer.errors)
                except IntegrityError as e:
                    logger.error(f"Integrity error: {e}")
                    return Response(
                        {
                            "detail": "Integrity error. Please ensure the data is unique."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                except Exception as e:
                    logger.error(f"An unexpected error occurred: {e}")
                    return Response(
                        {"detail": "An unexpected error occurred."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
        else:
            raise ValidationError(detail=user_serializer.errors)


class RiderRegistrationView(BaseUserRegistrationView):
    user_model = Rider
    serializer_class = RiderSerializer


class CustomerRegistrationView(BaseUserRegistrationView):
    user_model = Customer
    serializer_class = CustomerSerializer


class VerifyEmailView(APIView):
    """
    API view to handle email verification.
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests. Validate the verification token, mark the user's email as
        verified if the token is valid, and return a response with a success message or
        error message.
        """
        otp_token = request.data.get("otp_token")

        if not otp_token:
            return Response(
                {"detail": "OTP token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user_verification = UserVerification.objects.filter(
                email_otp__exact=otp_token
            ).first()
        except UserVerification.DoesNotExist:
            return Response(
                {"detail": "Invalid OTP token"}, status=status.HTTP_400_BAD_REQUEST
            )
        if user_verification and (
            user_verification.email_expiration_time > timezone.now()
            and not user_verification.user.is_verified
        ):
            # Mark the user as verified
            user_verification.user.is_verified = True
            user_verification.user.save()

            # Invalidate the OTP token
            user_verification.email_otp = None
            user_verification.email_expiration_time = None
            user_verification.save()

            return Response(
                {"detail": "Email verification successful"}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"detail": "Invalid or expired OTP token"},
                status=status.HTTP_400_BAD_REQUEST,
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


class LoginView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get("email")
        password = request.data.get("password")

        if email is None or password is None:
            return Response(
                {"detail": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, email=email, password=password)

        if user is None:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check if the user's email is verified
        if not user.is_verified:
            return Response(
                {"detail": "Email is not verified."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        tokens = create_jwt_pair_for_user(user)
        return Response(tokens, status=status.HTTP_200_OK)
