import requests
import logging


class TomTomDistanceMatrix:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.tomtom.com/routing/matrix/2/async"
        self.logger = logging.getLogger(__name__)

    def post_async_matrix(self, origin, riders_locations_data):
        """
        Post distance and duration between origin and multiple riders_locations_data using TomTom Matrix API.

        Args:
            origin (str): Origin coordinates in the format 'longitude,latitude'.
            riders_locations_data (list of dict): List of dictionaries, each containing 'email' and 'location' keys.
                                    'location' is a string in the format 'longitude,latitude'.

        Returns:
            str: JSON response from the API containing jobId and state.
        """
        try:
            origin_long, origin_lat = map(float, origin.split(","))
            if not riders_locations_data:
                self.logger.warning("No rider locations provided.")
                return None

            rider_locations = [
                {
                    "point": {
                        "latitude": float(item["location"].split(",")[1]),
                        "longitude": float(item["location"].split(",")[0]),
                    }
                }
                for item in riders_locations_data
            ]

            payload = {
                "origins": [
                    {"point": {"latitude": origin_lat, "longitude": origin_long}}
                ],
                "destinations": rider_locations,
                "options": {"routeType": "fastest", "vehicleMaxSpeed": 120},
            }
            headers = {"Content-Type": "application/json"}

            url = f"{self.base_url}?key={self.api_key}"
            response = requests.post(url, headers=headers, json=payload)

            if response.status_code == 202:
                return response.json()
            else:
                self.logger.error(
                    f"Failed to post async matrix. Status code: {response.status_code}"
                )
                raise Exception(
                    f"Failed to post async matrix. Status code: {response.status_code}. Error: {response.text}"
                )

        except Exception as e:
            self.logger.exception(f"Error occurred while posting async matrix: {e}")
            raise e

    def get_async_response(self, origin, riders_locations_data):
        """
        Get distance and duration between origin and multiple riders_locations using TomTom Matrix API.

        Args:
        - origin (str): Origin coordinates in the format 'longitude,latitude'.
        - riders_locations (list of dict): List of dictionaries, each containing 'email' and 'location' keys.
                                    'location' is a string in the format 'longitude,latitude'.

        Returns:
        - List of dictionaries: List of dictionaries, each containing 'email', 'distance' (in meters), and
                                'duration' (in minutes) for each location.
        """
        try:
            results = []
            post_response = self.post_async_matrix(origin, riders_locations_data)
            if not post_response:
                return None

            job_id = post_response.get("jobId")
            url = f"{self.base_url}/{job_id}/result"
            params = {"key": self.api_key}

            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json().get("data", [])

                for i, item in enumerate(data):
                    route_summary = item.get("routeSummary", {})
                    distance = route_summary.get("lengthInMeters", 0)
                    duration = route_summary.get("travelTimeInSeconds", 0)

                    formatted_duration = self.format_duration(duration)
                    results.append(
                        {
                            "email": riders_locations_data[i]["email"],
                            "distance": distance,
                            "duration": formatted_duration,
                        }
                    )

                return results
            else:
                self.logger.error(
                    f"Failed to get async response. Status code: {response.status_code}"
                )
                raise Exception(
                    f"Failed to get async response. Status code: {response.status_code}. Error: {e}"
                )

        except Exception as e:
            self.logger.exception(f"Error occurred while getting async response: {e}")
            raise e

    @staticmethod
    def format_duration(duration: int) -> str:
        """
        Format a duration in seconds into a human-readable format.

        Parameters:
        - duration (int): The duration in seconds.

        Returns:
        - str: The formatted duration string.
        """
        duration_minutes, duration_seconds = divmod(duration, 60)

        if duration <= 60:
            return f"{duration} secs"
        elif duration_seconds == 0:
            return f"{duration_minutes} minutes"
        else:
            return f"{duration_minutes} mins {duration_seconds} secs"
