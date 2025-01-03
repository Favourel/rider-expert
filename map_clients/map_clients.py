from django.conf import settings
import logging
import requests
from accounts.utils import retry
from map_clients.models import MapClientManager

from mapbox_distance_matrix.distance_matrix import MapboxDistanceDuration
from tom_tom_map_api.distance_matrix import TomTomDistanceMatrix

logger = logging.getLogger(__name__)


class MapClients:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.is_available = True

    def get_distances_duration(self):
        raise NotImplementedError("Subclasses must implement this method")

    def handle_exceptions(self, exception):
        if isinstance(exception, requests.exceptions.RequestException) or isinstance(
            exception, FileNotFoundError
        ):
            pass
        else:
            self.is_available = False


class Mapbox(MapClients):
    def __init__(self, api_key=None):
        if api_key is None:
            api_key = settings.MAPBOX_API_KEY
        super().__init__(api_key)

    @retry(
        (requests.exceptions.RequestException, FileNotFoundError),
        tries=3,
        delay=1,
        backoff=2,
        logger=logger,
    )
    def get_distances_duration(
        self,
        origin,
        destination,
    ):
        """
        A method that uses retry decorator to make multiple attempts to get distances and durations between two locations using MapBox API.

        :param origin: The origin of the distance calculation.
        :type origin: str
        :param destination: The destination of the distance calculation.
        :type destination: str
        :return: The get_distance_duration method of the mapbox client
        """
        try:
            mapbox = MapboxDistanceDuration(self.api_key)
            return mapbox.get_distance_duration(origin, destination)
        except Exception as e:
            self.handle_exceptions(e)


class TomTom(MapClients):
    def __init__(self, api_key=None):
        if api_key is None:
            api_key = settings.TOMTOM_API_KEY
        super().__init__(api_key)

    @retry(
        (requests.exceptions.RequestException, FileNotFoundError),
        tries=3,
        delay=1,
        backoff=2,
        logger=logger,
    )
    def get_distances_duration(
        self,
        origin,
        destination,
    ):
        """
        A method that uses retry decorator to make multiple attempts to get distances and durations between two locations using TomTom API.

        Parameters:
            origin (str): The starting location.
            destination (str): The destination location.

        Returns:
            func: the get_async_response method of the tomtom client
        """
        try:
            tomtom = TomTomDistanceMatrix(self.api_key)
            return tomtom.get_async_response(origin, destination)
        except Exception as e:
            self.handle_exceptions(e)


class MapClientsManager:
    def __init__(self):
        self.map_client_names = ["tomtom", "mapbox"]
        self.map_client = MapClientManager()
        self.client_name = self.map_client.current_map_client

    def get_client(self, client_name=None):
        """
        Get the client based on the client name.

        Args:
            client_name (str, optional): The name of the client. Defaults to None.

        Returns:
            Mapbox or TomTom: The client object based on the client_name.

        Raises:
            ValueError: If the client_name is not "mapbox" or "tomtom".
        """
        if client_name is None:
            client_name = self.client_name

        if client_name == "mapbox":
            return Mapbox()
        elif client_name == "tomtom":
            return TomTom()
        else:
            raise ValueError(f"Unknown client: {client_name}")

    def switch_client(self):
        """
        Switches to the next available client and saves the change.
        """
        current_client = self.get_client()
        if not current_client.is_available:
            current_index = self.map_client_names.index(self.client_name)
            next_index = (current_index + 1) % len(self.map_client_names)
            next_client_name = self.map_client_names[next_index]
            self.map_client.current_map_client = next_client_name
            self.map_client.save()
            logger.info(f"Switched to {next_client_name}, {self.client_name} is down")


# def get_distance(origin, destination):
#     api = settings.MAPBOX_API_KEY
#     url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{origin};{destination}?access_token={api}"
#
#     response = requests.get(url)
#
#     if response.status_code == 200:
#         data = response.json()
#         distance = data["routes"][0]["distance"]
#         return round((distance / 1000), 2)
#     else:
#         raise Exception(
#             f"Failed to get response. Status code: {response.status_code}. Error: {response.text}"
#         )

MAX_DISTANCE_KM = 5  # Maximum allowable distance in kilometers


def validate_coordinates(coordinates):
    try:
        longitude, latitude = map(float, coordinates.split(","))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Coordinates are out of valid range.")
        return True
    except (ValueError, TypeError):
        return False


def get_distance(origin, destination):
    api = settings.MAPBOX_API_KEY
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{origin};{destination}?access_token={api}"

    try:
        response = requests.get(url, timeout=10)  # Added timeout for reliability
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx, 5xx)

        data = response.json()
        if "routes" in data and len(data["routes"]) > 0:
            distance = data["routes"][0].get("distance")
            if distance is not None:
                return round(distance / 1000, 2)
            else:
                raise ValueError("Distance data is missing in the API response.")
        else:
            raise ValueError("No valid routes found in the API response.")
    except requests.exceptions.RequestException as e:
        # Log the detailed error for debugging
        logger.error(f"Mapbox API error: {str(e)} | URL: {url}")

        # Return a generic error message to the user
        raise ValueError("Unable to calculate distance. Please try again later.")


def validate_single_order(order):
    """
    Validate the distance between a pickup point and a single destination.

    Args:
        order (dict): Order data containing pickup and recipient details.

    Returns:
        dict: Error details if the delivery exceeds the maximum allowable distance,
              or a success message if valid.
    """
    try:
        # order = serializer.serialized_data
        pickup_coords = f"{order['pickup_long']},{order['pickup_lat']}"
        recipient_coords = f"{order['recipient_long']},{order['recipient_lat']}"

        # Calculate distance between pickup and recipient
        distance_km = get_distance(pickup_coords, recipient_coords)

        return {
            "status": "The delivery location is within the allowable distance.",
            "details": {
                "recipient_name": order["recipient_name"],
                "recipient_address": order["recipient_address"],
                "distance_km": distance_km,
            },
        }
    except ValueError as e:
        return {
            "error": "Failed to validate the delivery location.",
            "details": str(e),
            "suggestion": "Please ensure the provided coordinates are accurate and try again."
        }


def validate_distances(pickup_coords, destinations):
    """
    Validate the distances between a pickup point and multiple destinations.

    Args:
        pickup_coords (str): Pickup point coordinates in "longitude,latitude" format.
        destinations (list): List of destination dictionaries with required fields.

    Returns:
        dict: Summary of errors if any destination exceeds the maximum allowable distance.
    """
    errors = []

    for destination in destinations:
        try:
            distance_km = get_distance(pickup_coords, f"{destination['long']},{destination['lat']}")
            if distance_km > MAX_DISTANCE_KM:
                errors.append({
                    "recipient_name": destination["recipient_name"],
                    "recipient_address": destination["recipient_address"],
                    "distance_km": distance_km,
                    "message": (
                        f"This location is {distance_km} km away, exceeding the "
                        f"maximum allowable distance of {MAX_DISTANCE_KM} km."
                    ),
                })
        except ValueError as e:
            errors.append({
                "recipient_name": destination["recipient_name"],
                "recipient_address": destination["recipient_address"],
                # "distance_km": None,
                "message": f"Failed to calculate distance. Error: {str(e)}"
            })

    if errors:
        return {
            "error": "Some delivery locations are too far from the pickup point or delivery point.",
            "details": errors,
            "suggestion": (
                "Please split the delivery into smaller batches or ensure all "
                "destinations are within 5 km from the pickup point."
            ),
        }
    return {"status": "All destinations are within the allowable distance."}
