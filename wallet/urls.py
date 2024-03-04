from django.urls import path
from wallet import webhook as wh
from .views import *

urlpatterns = [
    path("wallet-wh/", wh.PaystackWebhookView.as_view(), name="wallet-wh"),
]
