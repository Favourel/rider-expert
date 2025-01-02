import decimal
from django.utils import timezone
from decimal import Decimal
from accounts.models import Rider
from django.db import transaction
from django.db.models import Avg, Q

from django.shortcuts import get_object_or_404
from accounts.utils import (
    DistanceCalculator,
    generate_otp,
    send_customer_notification,
    send_riders_notification,
    str_to_bool,
)
from map_clients.map_clients import MapClientsManager, get_distance, validate_distances, validate_single_order, \
    validate_coordinates
from map_clients.supabase_query import SupabaseTransactions
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from multi_orders.models import OrderRiderAssignment
from multi_orders.views import BulkOrderAssignmentView, AcceptOrDeclineOrderAssignmentView
from wallet.models import PendingWalletTransaction, WalletTransaction
from .models import DeclinedOrder, Order
from accounts.models import Rider
from .serializers import (
    OrderDetailUserSerializer,
    OrderSerializer,
    OrderDetailSerializer,
)
import logging


map_clients_manager = MapClientsManager()
supabase = SupabaseTransactions()

logger = logging.getLogger(__name__)


def get_rider_available(SEARCH_RADIUS_KM, order_location):
    fields = ["rider_email", "current_lat", "current_long"]
    riders_location_data = supabase.get_supabase_riders(fields=fields)

    distance_calc = DistanceCalculator(order_location)
    riders_within_radius = distance_calc.destinations_within_radius(
        riders_location_data, SEARCH_RADIUS_KM
    )
    return riders_within_radius


def get_ride_average_cost(riders_within_radius, order_location, recipient_location):
    rider_emails = [rider["email"] for rider in riders_within_radius]

    # Query Rider model to get charge_per_km for riders within radius
    riders_within_radius_queryset = Rider.objects.filter(user__email__in=rider_emails)
    average_charge_per_km = riders_within_radius_queryset.aggregate(
        avg_charge=Avg("charge_per_km")
    )["avg_charge"]

    trip_distance = get_distance(order_location, recipient_location)

    # Convert trip_distance to Decimal
    trip_distance_decimal = Decimal(str(trip_distance))

    # Calculate the cost based on the average charge_per_km and trip_distance
    cost = round((average_charge_per_km * trip_distance_decimal), 2)

    return cost


class CreateOrderView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        try:
            is_bulk = request.data.get("is_bulk")
            if is_bulk is None:
                return Response(
                    {"error": "'is_bulk' field is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = OrderSerializer(data=request.data)

            if serializer.is_valid():
                serializer.validated_data["customer"] = request.user.customer
                if is_bulk:
                    return self.create_bulk_order(serializer, request)
                else:
                    return self.create_single_order(serializer, request)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error in CreateOrderView: {str(e)}")
            return Response(
                {"error": "An unexpected error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def create_single_order(self, serializer, request):
        recipient_lat = request.data.get("recipient_lat")
        recipient_long = request.data.get("recipient_long")

        pickup_lat = request.data.get("pickup_lat")
        pickup_long = request.data.get("pickup_long")

        order_location = f"{pickup_long},{pickup_lat}"
        recipient_location = f"{recipient_long},{recipient_lat}"

        if not (validate_coordinates(order_location) and validate_coordinates(recipient_location)):
            raise ValueError("Invalid coordinates provided.")

        # Validate route distances
        route_errors = validate_single_order(serializer.validated_data)
        if "error" in route_errors:
            return Response(
                {
                    "error": "Some delivery locations are too far from the pickup point.",
                    "details": route_errors,

                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        riders_within_radius = get_rider_available(self.SEARCH_RADIUS_KM, order_location)

        if riders_within_radius:
            cost = get_ride_average_cost(riders_within_radius, order_location, recipient_location)
            serializer.save()
            response_data = serializer.data
            response_data["cost"] = cost
            return Response(response_data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {"error": "No riders found within the search radius."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def create_bulk_order(self, serializer, request):
        destinations = request.data.get("destinations", [])
        pickup_lat = request.data.get("pickup_lat")
        pickup_long = request.data.get("pickup_long")
        pickup_address = request.data.get("pickup_address")

        # Validate that the destinations and total weight are provided
        if not destinations:
            return Response({"error": "Invalid bulk order data."}, status=status.HTTP_400_BAD_REQUEST)

        for destination in destinations:
            required_fields = ["lat", "long", "recipient_name", "recipient_address", "recipient_phone_number",
                               "package_name", "package_weight", "fragile"]
            missing_fields = [field for field in required_fields if field not in destination]
            if missing_fields:
                return Response(
                    {
                        "error": f"Each destination must include the following fields: {', '.join(required_fields)}. "
                                 f"Missing: {', '.join(missing_fields)}"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Validate pickup details
        if not all([pickup_lat, pickup_long, pickup_address]):
            return Response({"error": "Pickup location details are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Riders and cost calculation
        order_location = f"{pickup_long},{pickup_lat}"
        riders_within_radius = get_rider_available(self.SEARCH_RADIUS_KM, order_location)
        if not riders_within_radius:
            return Response({"error": "No riders found within the search radius."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate route distances
        route_errors = validate_distances(order_location, destinations)
        if "error" in route_errors:
            return Response(
                {
                    "error": "Some delivery locations are too far from the pickup point.",
                    "details": route_errors,

                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        # Calculate costs and save bulk order
        costs = []
        for destination in destinations:
            recipient_location = f"{destination['long']},{destination['lat']}"
            cost = get_ride_average_cost(riders_within_radius, order_location, recipient_location)
            costs.append(cost)

        bulk_order = serializer.save(is_bulk=True)
        # bulk_order = serializer.save(is_bulk=True, weight=weight, pickup_address=pickup_address)

        # Distribute the total weight evenly across destinations
        # weight_per_destination = weight // len(destinations)
        # remaining_weight = weight % len(destinations)

        sub_orders = []
        for index, destination in enumerate(destinations):
            # Assign the remaining weight to the last destination
            # assigned_weight = weight_per_destination + (remaining_weight if index == len(destinations) - 1 else 0)

            sub_orders.append(
                OrderRiderAssignment(
                    customer=bulk_order.customer,
                    order=bulk_order,

                    package_name=destination["package_name"],
                    package_weight=Decimal(destination["package_weight"]),
                    price=costs[index],
                    fragile=destination["fragile"],

                    recipient_name=destination["recipient_name"],
                    recipient_address=destination["recipient_address"],
                    recipient_lat=destination["lat"],
                    recipient_long=destination["long"],
                    recipient_phone_number=destination["recipient_phone_number"],

                    pickup_address=pickup_address,
                    pickup_lat=pickup_lat,
                    pickup_long=pickup_long,

                    # assigned_weight=assigned_weight,
                    # fragile=bulk_order.fragile,
                    sequence=index + 1,
                    status="Pending",

                )
            )

        # Save all sub-orders in bulk
        OrderRiderAssignment.objects.bulk_create(sub_orders)

        return Response(
            {
                "message": "Bulk order created successfully.",
                "bulk_order_id": bulk_order.id,
                "total_cost": round(sum(costs), 2),
                "destinations": [
                    {
                        "recipient_name": destination["recipient_name"],
                        "recipient_address": destination["recipient_address"],
                        "price": costs[index],
                        # "assigned_weight": sub_orders[index].assigned_weight,

                        "weight": Decimal(destination["package_weight"]),
                        "fragile": destination.get("fragile"),
                        "package_name": destination["package_name"],
                    }
                    for index, destination in enumerate(destinations)
                ],
            },
            status=status.HTTP_201_CREATED,
        )


class GetAvailableRidersView(APIView):
    permission_classes = [IsAuthenticated]
    SEARCH_RADIUS_KM = 5  # Define the maximum search radius for riders in kilometers.

    def validate_parameters(self, price_offer, order, is_bulk):
        """
        Validate input parameters for the request.

        Parameters:
        - price_offer: The price the customer is willing to pay.
        - order: The order object to process.
        - is_bulk: Boolean flag indicating if the order is a bulk order.

        Returns:
        - Tuple (is_valid: bool, message: str): Validation status and error message if invalid.
        """
        try:
            # Ensure the price offer is a valid float.
            price_offer = float(price_offer)
        except ValueError as e:
            logger.error(e)
            return False, f"Invalid or missing price parameter: {e}"

        # Ensure the order is valid and handle bulk order-specific validations.
        if not isinstance(order, Order):
            return False, "Invalid or missing order parameter"

        if not all(isinstance(param, (float, int)) for param in [price_offer]):
            return False, "Invalid or missing parameters"

        if is_bulk:
            if not order.destinations or not isinstance(order.destinations, list):
                return False, "Missing or invalid destinations for bulk order"
            if any(package.package_weight <= 0 for package in order.assignments.all()):
                return False, "Invalid total weight for bulk order"

        return True, ""

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests to fetch available riders for an order.

        Parameters:
        - request: The HTTP request object.

        Returns:
        - Response: Contains the status, available riders, or error message.
        """
        try:
            # Get parameters from the request
            price_offer = request.GET.get("price")
            order_id = request.GET.get("order_id")
            order = get_object_or_404(Order, id=int(order_id))  # Fetch the order by ID or return 404 if not found.

            is_bulk = order.is_bulk  # Check if the order is a bulk order.

            # Validate parameters
            is_valid, validation_message = self.validate_parameters(price_offer, order, is_bulk)
            if not is_valid:
                return Response(
                    {"status": "error", "message": validation_message}, status=status.HTTP_400_BAD_REQUEST
                )

            # Extract customer and order details
            customer = request.user.customer
            origin_lat = order.pickup_lat
            origin_long = order.pickup_long
            is_fragile = order.fragile

            # Format origin coordinates for distance calculations
            origin = f"{origin_long},{origin_lat}"

            # Fetch rider location data from the Supabase service
            fields = ["rider_email", "current_lat", "current_long"]
            riders_location_data = supabase.get_supabase_riders(fields=fields)

            # Filter riders based on item weight, capacity, and fragility
            fragile_query = {"fragile_item_allowed": True} if is_fragile else {}
            from django.db.models import Q

            if is_bulk:
                weights = [package.package_weight for package in order.assignments.all()]
                rider_queryset = Rider.objects.filter(
                    user__email__in=[rider["email"] for rider in riders_location_data],
                    **fragile_query,
                ).filter(
                    Q(min_capacity__lte=min(weights), max_capacity__gte=max(weights))
                )
            else:
                rider_queryset = Rider.objects.filter(
                    user__email__in=[rider["email"] for rider in riders_location_data],
                    min_capacity__lte=order.weight,
                    max_capacity__gte=order.weight,
                    **fragile_query,
                )

            # Create a mapping of rider emails to Rider objects for efficient lookup
            rider_email_to_rider = {rider.user.email: rider for rider in rider_queryset}

            # Compile a list of riders with their current locations
            riders = []
            for rider in riders_location_data:
                rider_email = rider["email"]
                if rider_email in rider_email_to_rider:
                    riders.append({
                        "email": rider_email,
                        "location": f"{rider['current_long']},{rider['current_lat']}"
                    })

            # If no riders are found, send a notification to the customer
            if not riders or not origin:
                send_customer_notification.delay(
                    customer=customer.user.email, message="No rider found within radius"
                )
                return Response(
                    {"status": "error", "message": "No riders found within search radius."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Handle single or bulk order logic
            destinations = (
                [origin] + [f"{dest['long']},{dest['lat']}" for dest in order.destinations]
                if is_bulk else [f"{order.recipient_long},{order.recipient_lat}"]
            )

            # Use the DistanceCalculator to find riders within the search radius
            calculator = DistanceCalculator(origin)
            locations_within_radius = calculator.destinations_within_radius(riders, self.SEARCH_RADIUS_KM)

            # If no locations are within the radius, notify the customer
            if not locations_within_radius:
                send_customer_notification.delay(
                    customer=customer.user.email, message="No rider around you"
                )
                return Response(
                    {"status": "error", "message": "No riders found within search radius."},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Use Matrix API to calculate distances and durations for riders and destinations
            try:
                results = self.get_matrix_results(origin, locations_within_radius)
            except Exception as e:
                # Handle API errors gracefully by switching clients and retrying
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                results = self.get_matrix_results(origin, locations_within_radius)

            # Send notifications to riders with the order details and price offer
            send_riders_notification.delay(
                results,
                price=price_offer,
                request_coordinates={"long": origin_long, "lat": origin_lat},
                order_id=order_id,
            )

            # Update order status to indicate that rider search has started
            order.status = "RiderSearch"
            order.save()

            # Serialize the order data to include in the response
            order_data = OrderDetailUserSerializer(order).data

            # Return a success response
            return Response(
                {
                    **order_data,
                    "status": "success",
                    "order_status": order.status,
                    "message": "Notification sent successfully",
                }
            )

        except Exception as e:
            logger.error(f"Error in GetAvailableRidersView: {str(e)}")
            return Response(
                {"error": "An unexpected error occurred.", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def get_matrix_results(self, origin, destinations):
        """
        Fetch distance and duration data from a Matrix API.

        Parameters:
        - origin: The starting point of the trip.
        - destinations: List of destination coordinates.

        Returns:
        - results: API response containing distances and durations.
        """
        # Use the map client to get distances and durations
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id, *args, **kwargs):
        order = get_object_or_404(Order, id=order_id)
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GetOrderDetailByUser(APIView):
    SEARCH_RADIUS_KM = 5
    permission_classes = [IsAuthenticated]

    def get(self, request, email, *args, **kwargs):
        print(email)
        user_type = request.GET.get("user_type")
        order = Order.objects.filter(
            Q(customer__user__email=email) | Q(rider__user__email=email)
        )
        if order:
            order = order.latest("created_at")
            extra_data = {}
            if user_type == "customer":
                order_location = f"{order.pickup_long},{order.pickup_lat}"
                recipient_location = f"{order.recipient_long},{order.recipient_lat}"
                available_riders = get_rider_available(
                    self.SEARCH_RADIUS_KM, order_location
                )
                cost = get_ride_average_cost(
                    available_riders, order_location, recipient_location
                )
                extra_data["cost"] = cost

            serializer = OrderDetailUserSerializer(order)
            return Response(
                {**serializer.data, **extra_data}, status=status.HTTP_200_OK
            )
        else:
            return Response({"message": "Order not found"}, status=status.HTTP_200_OK)


class AcceptOrDeclineOrderView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        order_id = request.data.get("order_id")
        price = request.data.get("price")
        accept = request.data.get("accept")
        reason = request.data.get("reason")

        if not order_id:
            return Response(
                {"error": "Order ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get authenticated rider from request
        rider = request.user.rider_profile
        order = get_object_or_404(Order, id=order_id)

        # Call the bulk order app
        if order.is_bulk:
            return AcceptOrDeclineOrderAssignmentView().post(request, *args, **kwargs)

        if accept and reason is None:
            pickup_lat = order.pickup_lat
            pickup_long = order.pickup_long
            recipient_long = order.recipient_long
            recipient_lat = order.recipient_lat

            order_location = f"{pickup_long},{pickup_lat}"
            recipient_location = f"{recipient_long},{recipient_lat}"

            conditions = [{"column": "rider_email", "value": rider.user.email}]
            fields = ["rider_email", "current_lat", "current_long"]

            rider_data = supabase.get_supabase_riders(
                conditions=conditions, fields=fields
            )

            try:
                result = self.get_matrix_results(order_location, rider_data)
            except Exception as e:
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                result = self.get_matrix_results(order_location, rider_data)

            distance = result[0]["distance"]
            duration = result[0]["duration"]

            trip_distance = get_distance(order_location, recipient_location)

            # Calculate the cost of the ride based on the distance of the trip
            cost_of_ride = round((float(rider.charge_per_km) * trip_distance), 2)

            rider_info = {
                "rider_name": rider.user.get_full_name,
                "rider_email": rider.user.email,
                "vehicle_number": rider.vehicle_registration_number,
                "rating": rider.ratings if rider.ratings is not None else 0,
                "distance": distance,
                "duration": duration,
                "order_completed": rider.completed_orders,
                "price": price if price else cost_of_ride,
            }
            send_customer_notification.delay(
                customer=order.customer.user.email,
                message="Notifying riders close to you",
                rider_info=rider_info,
            )

            # Return a success message
            return Response(
                {"message": "Notification sent successfully"},
                status=status.HTTP_201_CREATED,
            )
        elif reason and not accept:
            rider.declined_requests += 1
            rider.save()
            # Create and save DeclinedOrder instance
            DeclinedOrder.objects.create(
                order=order,
                customer=None,
                rider=rider,
                decline_reason=reason,
            )

            # Return response for declined order
            return Response(
                {"message": "Order declined successfully"},
                status=status.HTTP_201_CREATED,
            )

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class AssignOrderToRiderView(APIView):
    """
    This view assigns an order to a rider.
    """

    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        """
        This method handles the POST request to assign an order to a rider.
        It assigns the rider to the order, updates the order status, and sends notifications to both the rider and the customer.
        """

        rider_email = request.data.get("rider_email")
        order_id = request.data.get("order_id")
        price = request.data.get("price")
        wallet = request.user.wallet

        if wallet.balance < decimal.Decimal(price):
            return Response(
                {"error": "Insufficient balance"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            # Get the order and rider objects
            order = get_object_or_404(Order, id=order_id)
            rider = get_object_or_404(Rider, user__email=rider_email)

            # Assign the rider to the order and update the order status
            order.rider = rider
            order.status = "WaitingForPickup"

            # Get the order location
            order_location = f"{order.pickup_long},{order.pickup_lat}"

            # Define conditions and fields for retrieving rider data from supabase
            conditions = [{"column": "rider_email", "value": rider_email}]
            fields = ["rider_email", "current_lat", "current_long"]

            # Retrieve rider data from supabase
            rider_data = supabase.get_supabase_riders(
                conditions=conditions, fields=fields
            )

            try:
                # Get distance and duration from the matrix results
                result = self.get_matrix_results(order_location, rider_data)
            except Exception as e:
                # Handle exception and retry
                logger.error(f"Error processing API request: {str(e)}")
                map_clients_manager.switch_client()
                result = self.get_matrix_results(order_location, rider_data)

            # Extract distance and duration from the result
            distance = result[0]["distance"]
            duration = result[0]["duration"]

            # Send notification to the rider
            rider_message = (
                f"Order Accepted: Order is {distance} km and {duration} away"
            )

            # Generate order_completion code
            code = generate_otp(length=4)

            # Update the order price and save the order
            wallet.balance -= decimal.Decimal(price) * 100
            wallet.updated_at = timezone.now()
            wallet.save()
            order.distance = distance
            order.duration = duration
            order.price = decimal.Decimal(price) * 100
            order.order_completion_code = code
            order.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="debit",
                amount=price,
                transaction_status="pending",
                created_at=timezone.now(),
                paid_at=timezone.now(),
            )

            PendingWalletTransaction.objects.create(
                user=request.user, order=order, amount=price
            )

            customer_message = f"Order Assigned successfully: {rider.user.get_full_name} is {distance} km and {duration} away. Order code: {code}"

            # Serialize the updated order and attach distance and duration
            serializer = OrderDetailSerializer(order)
            response_data = serializer.data
            response_data["distance"] = distance
            response_data["duration"] = duration

            send_riders_notification.delay(
                result,
                message=rider_message,
                order_id=order_id,
                price=price,
                order_info=response_data,
                request_coordinates={
                    "long": order.pickup_long,
                    "lat": order.pickup_lat,
                },
            )
            customer_message = f"Order Assigned successfully: {rider.user.get_full_name} is {distance} km and {duration} away"
            return Response(
                {
                    "message": customer_message,
                    **response_data,
                    "price": order.price,
                    "code": code,
                },
                status=status.HTTP_200_OK,
            )
        except (Rider.DoesNotExist, Order.DoesNotExist):
            # Handle if rider or order not found
            return Response("Rider or Order not found")

    def get_matrix_results(self, origin, destinations):
        """Get results from Matrix API."""
        map_client = map_clients_manager.get_client()
        results = map_client.get_distances_duration(origin, destinations)
        return results


class UpdateOrderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        order_id = request.data.get("order_id")
        order_status = request.data.get("status")
        order_code = request.data.get("order_code")

        if not order_id or not order_status:
            return Response(
                {"error": "Both order_id and status are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        if order_status not in valid_statuses:
            return Response(
                {"error": f"Invalid status: {order_status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order_status == "Delivered" and not order_code:
            return Response(
                {"error": "order_code is required for Delivered status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if the order exists
        order = get_object_or_404(Order, id=order_id)

        # Verify order code if required
        if order_status == "Delivered" and order.order_completion_code != order_code:
            return Response(
                {"error": "Invalid order code."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Update order status
        order.status = order_status
        order.save()

        send_customer_notification(
            customer=order.customer.user.email,
            message=f"Status update {order_status}",
            ride_status=order_status,
            by_pass_rider_info=True,
        )

        return Response(
            {
                "message": f"Order status updated to {order_status}.",
                "order_status": order_status,
            },
            status=status.HTTP_200_OK,
        )
