import requests
from django.conf import settings


class PaystackServices:
    def __init__(self, email, first_name, last_name, phone_number):
        self.api_key = settings.PAYSTACK_SECRET_KEY
        self.base_url = "https://api.paystack.co/customer"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.email = email
        self.first_name = first_name
        self.last_name = last_name
        self.phone_number = phone_number

    def create_customer(self):
        data = {
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone": self.phone_number,
        }
        response = requests.post(self.base_url, headers=self.headers, json=data)
        response.raise_for_status()
        data = response.json()
        return data

    def validate_customer(self, account_number, bank_code, bvn):

        url = f"{self.base_url}/{self.email}/identification"

        params = {
            "country": "NG",
            "type": "bank_account",
            "account_number": account_number,
            "bvn": bvn,
            "bank_code": bank_code,
            "first_name": self.first_name,
            "last_name": self.last_name,
        }

        response = requests.post(url, headers=self.headers, json=params)
        response.raise_for_status()
        data = response.json()
        return data

    def fetch_customer(self, email_or_code):
        url = f"{self.base_url}/:{email_or_code}"
        headers = {"Authorization": f"Bearer {self.api}"}

        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["data"]
