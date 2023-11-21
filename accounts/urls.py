# urls.py

from django.urls import path
from .views import RiderRegistrationView

urlpatterns = [
    path(
        "register_customer/", RegisterCustomerView.as_view(), name="register_customer"
    ),
    path('riders/register/', RiderRegistrationView.as_view(), name='rider-registration'),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
]
