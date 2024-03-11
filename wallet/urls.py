from django.urls import path
from wallet import webhook as wh
from .views import *

urlpatterns = [
    path("wallet-wh/", wh.PaystackWebhookView.as_view(), name="wallet-wh"),
    path(
        "get-wallet-balance/", GetWalletBalanceView.as_view(), name="get-wallet-balance"
    ),
    path(
        "debit-wallet-balance/",
        DebitWalletBalanceView.as_view(),
        name="debit-wallet-balance",
    ),
    path(
        "credit-rider-wallet/",
        CreditRiderWalletView.as_view(),
        name="credit-rider-wallet",
    ),
]
