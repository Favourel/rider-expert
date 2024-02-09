from . import views
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urlpatterns = [
    path("token/create", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify", TokenVerifyView.as_view(), name="token_verify"),
    path(
        "register_customer/",
        views.CustomerRegistrationView.as_view(),
        name="register_customer",
    ),
    path(
        "riders/register/",
        views.RiderRegistrationView.as_view(),
        name="rider-registration",
    ),
    path("verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
    path("login/", views.LoginView.as_view(), name="login"),
    path(
        "reset_password/", views.UserPasswordResetView.as_view(), name="reset_password"
    ),
    path(
        "available_rider/",
        views.GetAvailableRidersView.as_view(),
        name="available_rider",
    ),

]
