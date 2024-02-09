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
from mapbox_distance_matrix.distance_matrix import MapboxDistanceDuration
from google.cloud import firestore
from googlemaps.exceptions import ApiError
import firebase_admin
from firebase_admin import credentials, messaging

import logging

logger = logging.getLogger(__name__)

riderexpert_db = firestore.AsyncClient(project="riderexpert", database="riderexpert-db")

cred = credentials.Certificate("riderexpert-firebase-adminsdk-8eiae-55c277d9ed.json")
riderexpert_app = firebase_admin.initialize_app(cred)


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

    def get_mapbox_client(self):
        """Initialize and return the asynchronous Mapbox API client."""
        return MapboxDistanceDuration(api_key=settings.MAPBOX_API_KEY)

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

    def handle_mapbox_api_error(self, e):
        """Handle Mapbox API errors."""
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
        order_destination = request.GET.get("destination")

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
            mapbox = await sync_to_async(self.get_mapbox_client)()

            
            # Optimize Database Queries
            available_riders = await self.get_available_riders(
                gmaps, order_location, item_capacity, is_fragile
            )

            # Extract FCM tokens and send notifications
            await self.send_fcm_notifications(
                available_riders, order_location, order_destination, is_fragile
            )

            return Response(status=status.HTTP_201_CREATED)
        except ApiError as e:
            logger.error(f"Google Maps API error: {str(e)}")
            return self.handle_google_maps_api_error(e)
        except Exception as e:
            return self.handle_internal_error(e)

    async def get_available_riders(
        self, gmaps, order_location, item_capacity, is_fragile
    ):
        try:
            riders_collection = riderexpert_db.collection("riders").stream()

            rider_locations = []

            # Prepare a list of rider locations and emails
            emails = []
            async for firestore_rider in riders_collection:
                firestore_data = firestore_rider.to_dict()
                email = firestore_data.get("email")
                emails.append(email)
                rider_location = (
                    firestore_data.get("current_latitude"),
                    firestore_data.get("current_longitude"),
                )
                rider_locations.append(rider_location)

            # Fetch all riders in a single query
            riders = await sync_to_async(Rider.objects.filter)(
                user__email__in=emails,
                fragile_item_allowed=is_fragile,
                min_capacity__lte=item_capacity,
                max_capacity__gte=item_capacity,
            )

            batch_size = 20

            # Fetch all riders in batches only if the total number of riders is greater than batch_size
            if len(rider_locations) > batch_size:
                riders_within_radius = await self.fetch_riders_in_batches(
                    gmaps, order_location, rider_locations, batch_size, riders
                )
            else:
                riders_within_radius = await self.fetch_all_riders(
                    gmaps, order_location, rider_locations, riders
                )

            return riders_within_radius

        except ApiError as e:
            return self.handle_google_maps_api_error(e)

    async def fetch_riders_in_batches(
        self, gmaps, order_location, rider_locations, batch_size, riders
    ):
        riders_within_radius = []

        for i in range(0, len(rider_locations), batch_size):
            batch_destinations = rider_locations[i : i + batch_size]
            riders_within_radius += await self.process_distance_matrix_result(
                gmaps, order_location, batch_destinations, riders
            )

        return riders_within_radius

    async def fetch_all_riders(self, gmaps, order_location, rider_locations, riders):
        return await self.process_distance_matrix_result(
            gmaps, order_location, rider_locations, riders
        )

    async def process_distance_matrix_result(
        self, gmaps, order_location, destinations, riders
    ):
        riders_within_radius = []

        try:
            distance_matrix_result = await sync_to_async(gmaps.distance_matrix)(
                origins=order_location,
                destinations=destinations,
                mode="driving",
                units="metric",
            )
        except Exception as e:
            raise Exception(str(e))

        # Iterate over the response and filter out riders within the desired radius
        for i, distance_row in enumerate(distance_matrix_result["rows"]):
            for element in distance_row["elements"]:
                duration = element["duration"]["text"]
                distance = element["distance"]

                if distance["value"] <= self.SEARCH_RADIUS_METERS * 1000:
                    # Include both distance and duration in the response
                    rider_data = {
                        "rider": await sync_to_async(self.getRiderSerializer)(
                            await sync_to_async(lambda i: riders[i])(i)
                        ),
                        "distance": distance,
                        "duration": duration,
                    }
                    riders_within_radius.append(rider_data)

        # Sort the riders_within_radius list based on distance
        riders_within_radius.sort(key=lambda x: x["distance"]["value"])

        return riders_within_radius

    def getRiderSerializer(self, django_rider):
        return RiderSerializer(django_rider).data

    async def send_fcm_notifications(
        self, riders_within_radius, order_location, is_fragile
    ):
        # Extract all rider emails
        rider_emails = [
            rider_data["rider"]["user"]["email"] for rider_data in riders_within_radius
        ]

        # Fetch all FCM tokens for the given rider emails
        rider_tokens = await self.get_fcm_tokens_by_emails(rider_emails)

        # Construct FCM message
        message_data = {
            "order_location": order_location,
            "is_fragile": str(is_fragile),
            # Add any other relevant data to the message
        }

        # Send multicast FCM message
        message = messaging.MulticastMessage(data=message_data, tokens=rider_tokens)
        try:
            await sync_to_async(messaging.send_multicast)(message)
        except Exception as e:
            # Handle FCM sending error
            logger.error(f"FCM sending error: {str(e)}")

    async def get_fcm_tokens_by_emails(self, rider_emails):
        # Fetch FCM tokens from Firestore for multiple rider emails
        rider_tokens = []

        # Create a Firestore query for all riders with the specified emails
        riders_query = riderexpert_db.collection("riders").where(
            "email", "in", rider_emails
        )

        # Execute the query
        async for rider_snapshot in sync_to_async(riders_query.stream)():
            rider_data = rider_snapshot.to_dict()
            fcm_token = rider_data.get("fcm_token")
            rider_tokens.append(fcm_token)

        return rider_tokens
