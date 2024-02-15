import requests
import time


class MapboxDistanceDuration:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_distance_duration(self, origin, riders_locations):
        """
        Get distance and duration between origin and multiple riders_locations using Mapbox Matrix API.

        Args:
        - origin (str): Origin coordinates in the format 'longitude,latitude'.
        - riders_locations (list of dict): List of dictionaries, each containing 'email' and 'location' keys.
                                    'location' is a string in the format 'longitude,latitude'.

        Returns:
        - List of dictionaries: List of dictionaries, each containing 'email', 'distance' (in meters), and
                                'duration' (in minutes) for each location.
        """
        if len(riders_locations) == 0:
            return []

        # Maximum 10 riders_locations per request
        batch_size = 9
        num_batches = (len(riders_locations) + batch_size - 1) // batch_size

        results = []

        # Define the Mapbox Matrix API endpoint URL
        url_base = f"https://api.mapbox.com/directions-matrix/v1/mapbox/driving-traffic/{origin};"

        if num_batches == 1 and len(riders_locations) == 1:
            # Directly make a request without batching
            rider_location = riders_locations[0]
            destinations_str = rider_location["location"]
            url = f"{url_base}{destinations_str}?access_token={self.api_key}"
            response = requests.get(url)

            if response.status_code == 200:
                data = response.json()
                distance = data["destinations"][1]["distance"]
                duration = data["durations"][1][0]
                formatted_duration = self.format_duration(duration)
                results.append(
                    {
                        "email": rider_location["email"],
                        "distance": distance,
                        "duration": formatted_duration,
                    }
                )
            else:
                print("Error:", response.text)
        else:
            for i in range(num_batches):
                start_idx = i * batch_size
                end_idx = min((i + 1) * batch_size, len(riders_locations))
                batch_destinations = riders_locations[start_idx:end_idx]

                # Convert riders_locations list to a semicolon-separated string
                destinations_str = ";".join(
                    [
                        rider_location["location"]
                        for rider_location in batch_destinations
                    ]
                )

                # Make a GET request to the API
                url = f"{url_base}{destinations_str}?access_token={self.api_key}"
                response = requests.get(url)

                # Check if the request was successful (status code 200)
                if response.status_code == 200:
                    data = response.json()

                    # Extract distances and durations from the response
                    for j, destination in enumerate(data["destinations"][1:], start=1):
                        distance = destination["distance"]
                        duration = data["durations"][j][0]
                        formatted_duration = self.format_duration(duration)
                        results.append(
                            {
                                "email": batch_destinations[j - 1]["email"],
                                "distance": distance,
                                "duration": formatted_duration,
                            }
                        )

                else:
                    print("Error:", response.text)

                # Wait for a short interval to avoid hitting rate limits
                if i < num_batches - 1:
                    time.sleep(6)

        return results

    def format_duration(self, duration: int) -> str:
        """
        Format a duration in seconds into a human-readable format.

        Parameters:
        - duration (int): The duration in seconds.

        Returns:
        - str: The formatted duration string.
        """
        # Convert duration from seconds to minutes and seconds
        duration_minutes = int(duration // 60)
        duration_seconds = int(duration % 60)

        # Check if duration is less than or equal to 60 seconds
        if duration <= 60:
            duration_formatted = f"{duration} secs"
        elif duration_seconds == 0:
            duration_formatted = f"{duration_minutes} minutes"
        else:
            duration_formatted = (
                f"{duration_minutes} mins {duration_seconds} secs"
            )

        return duration_formatted