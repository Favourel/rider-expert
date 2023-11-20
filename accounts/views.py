from django.db import transaction, IntegrityError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.serializers import ValidationError
from .serializers import RiderSerializer, UserSerializer
from .models import Rider
# from .utils import send_welcome_email
import logging

logger = logging.getLogger(__name__)

class RiderRegistrationView(APIView):
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
                        
                        rider_obj = Rider.objects.create(user=user)
                        rider_serializer = RiderSerializer(rider_obj).data

                        if rider_serializer:
                            # rider = rider_serializer.save()

                            # Send welcome email or perform any additional actions
                            # send_welcome_email(user)

                            return Response(
                                {
                                    "data": rider_serializer,
                                    "message": "Rider registration successful",
                                },
                                status=status.HTTP_201_CREATED,
                            )
                        else:
                            raise ValidationError(detail=rider_serializer.errors)
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
