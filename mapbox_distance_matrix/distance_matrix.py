import requests
import time


class MapboxDistanceDuration:
    def __init__(self, api_key):
        self.api_key = api_key

    def get_distance_duration(self, origin, destinations):
        """
        Get distance and duration between origin and multiple destinations using Mapbox Matrix API.

        Args:
        - origin (str): Origin coordinates in the format 'longitude,latitude'.
        - destinations (list of str): List of destination coordinates in the format 'longitude,latitude'.

        Returns:
        - List of tuples: List of (distance in meters, duration in seconds) for each destination.
        """
        if len(destinations) == 0:
            return []

        # Maximum 10 destinations per request
        batch_size = 9
        num_batches = (len(destinations) + batch_size - 1) // batch_size

        results = []

        # Define the Mapbox Matrix API endpoint URL
        url_base = f"https://api.mapbox.com/directions-matrix/v1/mapbox/driving-traffic/{origin};"

        if num_batches == 1 and len(destinations) == 1:
            # Directly make a request without batching
            destinations_str = destinations[0]
            url = f"{url_base}{destinations_str}?access_token={self.api_key}"
            response = requests.get(url)

            if response.status_code == 200:
                data = response.json()
                distance = data["destinations"][0]["distance"]
                duration = data["durations"][0][0]
                results.append((distance, duration))
            else:
                print("Error:", response.text)
        else:
            for i in range(num_batches):
                start_idx = i * batch_size
                end_idx = min((i + 1) * batch_size, len(destinations))
                batch_destinations = destinations[start_idx:end_idx]

                # Convert destinations list to a semicolon-separated string
                destinations_str = ";".join(batch_destinations)

                # Make a GET request to the API
                url = f"{url_base}{destinations_str}?access_token={self.api_key}"
                response = requests.get(url)

                # Check if the request was successful (status code 200)
                if response.status_code == 200:
                    data = response.json()

                    # Extract distances and durations from the response
                    for j, destination in enumerate(data["destinations"]):
                        distance = destination["distance"]
                        duration = data["durations"][0][j]
                        results.append((distance, duration))
                else:
                    print("Error:", response.text)

                # Wait for a short interval to avoid hitting rate limits
                if i < num_batches - 1:
                    time.sleep(6)

        return results


# Example usage:
# origin = "-122.42,37.78"  # San Francisco, CA
# destinations = [
#     "-122.41,37.79",
#     "-122.40,37.80",
#     "-122.39,37.81",
# ]


# results = get_distance_duration(origin, destinations, api_key)
# print(results)
# if results is not None:
#     for i, (distance, duration) in enumerate(results):
#         print(f"Destination {i + 1}:")
#         print(f"Distance: {distance} meters")
#         print(f"Duration: {duration} seconds")
