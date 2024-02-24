from django.db import models
from accounts.models import Customer, Rider
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _


class Order(models.Model):
    STATUS_CHOICES = [
        ("PendingPickup", _("Pending Pickup")),
        ("WaitingForPickup", _("Waiting for pickup")),
        ("PickedUp", _("Picked up")),
        ("InTransit", _("In transit")),
        ("Arrived", _("Arrived")),
        ("Delivered", _("Delivered")),
        ("Failed", _("Failed")),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, blank=True, null=True)
    pickup_address = models.TextField()
    pickup_lat = models.FloatField(blank=True, null=True)
    pickup_long = models.FloatField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="PendingPickup"
    )
    recipients_name = models.CharField(max_length=100)
    recipient_address = models.TextField()
    recipient_lat = models.FloatField(blank=True, null=True)
    recipient_long = models.FloatField(blank=True, null=True)
    recipient_phone_number = models.CharField(max_length=15)
    order_completion_code = models.CharField(max_length=10, unique=True)
    parcel_weight = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    parcel_value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    fragile = models.BooleanField(default=False)

    def __str__(self):
        return f"Order {self.pk} - {self.status}"
