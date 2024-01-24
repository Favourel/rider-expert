from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone
from .managers import CustomUserManager
from django.core.validators import EmailValidator


email_validator = EmailValidator(message="Enter a valid email address.")


class CustomUser(AbstractBaseUser, PermissionsMixin):
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    phone_number = models.CharField(max_length=15)
    email = models.EmailField(validators=[email_validator], unique=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True, null=True)
    last_login = models.DateTimeField(auto_now=True, null=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.email

    @property
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"


class UserVerification(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    otp = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    otp_expiration_time = models.DateTimeField(null=True, blank=True)


class Customer(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, primary_key=True)

    def __str__(self):
        return self.user.email


class Rider(models.Model):
    user = models.OneToOneField(
        CustomUser, on_delete=models.CASCADE, related_name="rider_profile"
    )
    vehicle_type = models.CharField(max_length=50, default="TWO_WHEELER")
    vehicle_registration_number = models.CharField(max_length=20, unique=True)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return self.user.email
