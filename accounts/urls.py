from django.urls import path
from .views import *

urlpatterns = [
    path(
        "register_customer/", RegisterCustomerView.as_view(), name="register_customer"
    ),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("resend-token/", ResendTokenView.as_view(), name="resend-token"),
]
