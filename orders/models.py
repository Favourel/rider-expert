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
        ("Created", _("Created")),
        ("RiderSearch", _("RiderSearch")),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)
    pickup_address = models.TextField()
    pickup_lat = models.FloatField(blank=True, null=True)
    pickup_long = models.FloatField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="Created"
    )
    recipient_name = models.CharField(max_length=100)
    recipient_address = models.TextField()
    recipient_lat = models.FloatField(blank=True, null=True)
    recipient_long = models.FloatField(blank=True, null=True)
    recipient_phone_number = models.CharField(max_length=15)
    order_completion_code = models.CharField(max_length=10, blank=True, null=True)
    weight = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    quantity = models.PositiveIntegerField(null=True, blank=True)
    value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    fragile = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.pk} - {self.status}"


class DeclinedOrder(models.Model):
    order = models.OneToOneField(Order, on_delete=models.CASCADE)
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=True, blank=True
    )
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, null=True, blank=True)
    decline_reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
