from django.conf import settings
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Order
from accounts.models import Rider


class AssignOrderToRiderAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_google_maps_client(self):
        """Initialize and return the asynchronous Google Maps API client."""
        return GoogleMapsClient(key=settings.GOOGLE_MAPS_API_KEY)

    def get_model_instance(self, model, id):
        model_instance = model.objects.get(id)
        return model_instance

    def post(self, request, order_id, rider_email):
        try:
            order = self.get_model_instance(Order, order_id)
            rider = self.get_model_instance(Rider, rider_email)
            order.rider = rider
            order_location = order.pickup_address
            order.status = "Waiting for pickup"

            gmaps = self.get_google_maps_client()
            rider_location = self.get_rider_location(rider_email)
            distance_matrix_result = self.get_distance_matrix(
                gmaps=gmaps,
                order_location=order_location,
                rider_location=rider_location,
            )
            order_data = {distance_matrix_result, order}
            order.save()
            return Response({"status": status.HTTP_200_OK, "riders": order_data})
        except (Rider.DoesNotExist, Order.DoesNotExist):
            return Response("Rider or Order not found")

    def get_rider_location(self, rider_email):
        try:
            rider_location_ref = riderexpert_db.collection("riders").document(
                rider_email
            )
            rider_location_data = rider_location_ref.get()

            rider_location = (
                rider_location_data.get("current_latitude"),
                rider_location_data.get("current_longitude"),
            )
            return rider_location
        except Exception as e:
            raise Exception(str(e))

    def get_distance_matrix(self, gmaps, order_location, rider_location):
        try:
            distance_matrix_result = gmaps.distance_matrix(
                origins=rider_location,
                destinations=order_location,
                mode="driving",
                units="metric",
            )
            distance = distance_matrix_result["rows"][0]["elements"][0]["distance"]
            duration = distance_matrix_result["rows"][0]["elements"][0]["duration"]
            return {"distance": distance, "duration": duration}
        except Exception as e:
            raise Exception(str(e))
