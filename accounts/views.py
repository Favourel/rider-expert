from asgiref.sync import sync_to_async
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import authenticate
from django.utils import timezone
from .tokens import create_jwt_pair_for_user
from adrf.views import APIView as AsyncAPIView
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import generics, status
from .serializers import *
from .models import *
from .utils import send_verification_email, str_to_bool
from django.conf import settings
from googlemaps import Client as GoogleMapsClient
from google.cloud import firestore
from googlemaps.exceptions import ApiError

import logging

logger = logging.getLogger(__name__)

riderexpert_db = firestore.AsyncClient(project="riderexpert", database="riderexpert-db")


class BaseRegistrationView(generics.CreateAPIView):
    serializer_class = None

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            send_verification_email(user.user, "registration")
            success_message = f"{str(user)} registered successfully"
            data = {
                "message": success_message,
                "data": serializer.data,
            }
            return Response(data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RiderRegistrationView(BaseRegistrationView):
    serializer_class = RiderSerializer


class CustomerRegistrationView(BaseRegistrationView):
    serializer_class = CustomerSerializer


class VerifyEmailView(APIView):
    """
    API view to handle email verification.
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests to validate the verification token, mark the user's email as verified,
        and return a response with a success message or error message.
        """

        # Get the otp_token from the request data
        otp_token = request.data.get("otp_token")

        # Check if otp_token is missing
        if not otp_token:
            return Response(
                {"detail": "OTP token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Query the UserVerification model for the given otp_token
            user_verification = UserVerification.objects.filter(
                otp__exact=otp_token
            ).first()
        except UserVerification.DoesNotExist:
            return Response(
                {"detail": "Invalid OTP token"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Check if user_verification exists and the email has not expired
        if user_verification and (
            user_verification.otp_expiration_time > timezone.now()
            and not user_verification.user.is_verified
        ):
            # Mark the user as verified
            user_verification.user.is_verified = True
            user_verification.user.save()

            # Invalidate the OTP token
            user_verification.otp = None
            user_verification.otp_expiration_time = None
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

        if user_verification.otp_expiration_time > timezone.now():
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
        """
        Handle POST requests to the API endpoint.

        Args:
            request: The request object containing the data.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            A response object with the appropriate tokens and status code.
        """
        # Get the email and password from the request data
        email = request.data.get("email")
        password = request.data.get("password")

        # Check if email or password is missing
        if not email or not password:
            return self.invalid_credentials_response()

        # Authenticate the user with the provided email and password
        user = authenticate(request, email=email, password=password)

        # Check if user is None (invalid credentials)
        if user is None:
            return self.invalid_credentials_response()

        # Check if user's email is not verified
        if not user.is_verified:
            return self.unverified_email_response()

        # Create JWT tokens for the authenticated user
        tokens = create_jwt_pair_for_user(user)

        # Return the tokens with a 200 OK status code
        return Response(tokens, status=status.HTTP_200_OK)

    def invalid_credentials_response(self):
        return Response(
            {"detail": "Invalid email or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    def unverified_email_response(self):
        return Response(
            {"detail": "Email is not verified."},
            status=status.HTTP_401_UNAUTHORIZED,
        )


class ForgotPasswordView(APIView):
    def post(self, request, *args, **kwargs):
        email = request.data.get("email")

        if not email:
            return Response(
                {"detail": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = CustomUser.objects.get(email=email)
        except ObjectDoesNotExist:
            return Response(
                {"detail": "User with this email does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )

        send_verification_email(user, purpose="forgot_password")

        return Response(
            {"detail": "An email with OTP has been sent to your email address"},
            status=status.HTTP_200_OK,
        )


class GetAvailableRidersView(AsyncAPIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_METERS = 10

    def get_google_maps_client(self):
        """Initialize and return the asynchronous Google Maps API client."""
        return GoogleMapsClient(key=settings.GOOGLE_MAPS_API_KEY)

    async def validate_parameters(self, order_location, item_capacity, is_fragile):
        """Validate input parameters."""
        try:
            item_capacity = float(item_capacity)
            is_fragile = str_to_bool(is_fragile)
        except (ValueError, TypeError):
            return False, "Invalid or missing parameters"

        if not all(
            [
                order_location is not None and isinstance(order_location, str),
                item_capacity is not None and isinstance(item_capacity, (int, float)),
                is_fragile is not None and isinstance(is_fragile, bool),
            ]
        ):
            return False, "Invalid or missing parameters"
        return True, ""

    def handle_google_maps_api_error(self, e):
        """Handle Google Maps API errors."""
        return Response(
            {"status": "error", "message": f"Google Maps API error: {str(e)}"},
            status=400,
        )

    def handle_internal_error(self, e):
        """Handle internal server errors."""
        logger.error(str(e))
        raise Exception(str(e))

    async def get(self, request, *args, **kwargs):
        order_location = request.GET.get("origin")
        item_capacity = request.GET.get("item_capacity")
        is_fragile = request.GET.get("is_fragile")

        # Handle Missing or Invalid Parameters
        is_valid, validation_message = await self.validate_parameters(
            order_location, item_capacity, is_fragile
        )
        if not is_valid:
            return Response(
                {"status": "error", "message": validation_message}, status=400
            )

        try:
            # Initialize asynchronous Google Maps API client
            gmaps = await sync_to_async(self.get_google_maps_client)()

            # Optimize Database Queries
            available_riders = await self.get_available_riders(
                gmaps, order_location, item_capacity, is_fragile
            )
            print("Available Riders: ", available_riders)
            return Response({"status": "success", "riders": available_riders})
        except ApiError as e:
            logger.error(f"Google Maps API error: {str(e)}")
            return self.handle_google_maps_api_error(e)
        except Exception as e:
            return self.handle_internal_error(e)

    def get_available_riders_django(self, email, is_fragile, item_capacity):
        queryset = Rider.objects.filter(
            user__email=email,
            is_available=True,
            fragile_item_allowed=is_fragile,
            min_capacity__lte=item_capacity,
            max_capacity__gte=item_capacity,
        )
        return queryset.exists(), queryset.first()

    async def get_available_riders(
        self, gmaps, order_location, item_capacity, is_fragile
    ):
        try:
            riders_collection = riderexpert_db.collection("riders").stream()

            riders_within_radius = []
            rider_locations = []

            # Prepare a list of rider locations
            async for firestore_rider in riders_collection:
                firestore_data = firestore_rider.to_dict()
                
                email = firestore_data.get("email")

                exists, django_rider = await sync_to_async(
                    self.get_available_riders_django
                )(email, is_fragile, item_capacity)

                if exists:
                    rider_location = (
                        firestore_data.get("current_latitude"),
                        firestore_data.get("current_longitude"),
                    )
                    rider_locations.append(rider_location)

            # Make a single call to the distance matrix API
            if rider_locations:
                origins = [order_location] * len(rider_locations)
                destinations = rider_locations

                distance_matrix_result = await sync_to_async(gmaps.distance_matrix)(
                    origins=origins,
                    destinations=destinations,
                    mode="driving",
                    units="metric",
                )
                print("Distance Matrix: ", distance_matrix_result)

                # Iterate over the response and filter out riders within the desired radius
                for i, distance_row in enumerate(distance_matrix_result["rows"]):
                    distance = distance_row["elements"][0]["distance"]
                    duration = distance_row["elements"][0]["duration"]["text"]
                    print(f"Rider {i} distance: {distance['text']}", f"Rider {i} duration: {duration}")

                    if distance["value"] <= self.SEARCH_RADIUS_METERS * 1000:
                        # Include both distance and duration in the response
                        rider_data = {
                            "rider": await sync_to_async(self.getRiderSerializer)(
                                django_rider
                            ),
                            "distance": distance,
                            "duration": duration,
                        }
                        riders_within_radius.append(rider_data)
            print("Riders: ", riders_within_radius)
            return riders_within_radius

        except ApiError as e:
            return self.handle_google_maps_api_error(e)

    def getRiderSerializer(self, django_rider):
        return RiderSerializer(django_rider).data
