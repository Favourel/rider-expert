from django.conf import settings
import logging
from supabase import create_client
from typing import List, Dict, Optional


logger = logging.getLogger(__name__)


class SupabaseTransactions:
    # Class attributes for Supabase URL and key
    supabase_url = settings.SUPABASE_URL
    supabase_key = settings.SUPABASE_KEY
    riders_table = "riders"
    customers_table = "customers"

    def __init__(self):
        self.supabase = create_client(self.supabase_url, self.supabase_key)

    def get_supabase_riders(
        self,
        conditions: Optional[List[Dict[str, str]]] = None,
        fields: Optional[List[str]] = None,
    ):
        try:
            query = self.supabase.table(self.riders_table)
            if fields is None:
                fields = ["*"]
            query = query.select(*fields)
            if conditions:
                for condition in conditions:
                    query = query.eq(condition["column"], condition["value"])

            response = query.execute()

            return [
                {
                    "email": rider["rider_email"],
                    "location": "{},{}".format(rider["current_long"], rider["current_lat"]),
                }
                for rider in response.data
            ]
        except Exception as e:
            self.handle_error(e)

    def send_riders_notification(self, riders):
        try:
            for rider in riders:
                rider_email = rider.get("email")
                distance = rider.get("distance")
                duration = rider.get("duration")
                if all([rider_email, distance is not None, duration is not None]):
                    message = f"New Delivery Request: Order is {distance} m and {duration} away"
                    self.supabase.table(self.riders_table).update(
                        {"broadcast_message": message}
                    ).eq("rider_email", rider_email).execute()
                else:
                    logger.warning(
                        "Invalid rider data: email, distance, or duration missing."
                    )
        except Exception as e:
            self.handle_error(e)

    def send_customer_notification(self, customer, message):
        try:
            self.supabase.table(self.customers_table).update(
                {"notification": message}
            ).eq("email", customer).execute()
        except Exception as e:
            self.handle_error(e)

    def handle_error(self, error):
        logger.error(f"Supabase API error: {str(error)}")
        raise error
