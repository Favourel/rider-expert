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
    def __init__(self, api_key):
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
