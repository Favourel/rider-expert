from django.core.validators import MinValueValidator
from django.db import models
from orders.models import Order
from accounts.models import Rider, Customer


# Create your models here.


class OrderRiderAssignment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="assignments")
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name="assignments", null=True, blank=True)

    package_name = models.CharField(max_length=255, null=True, blank=True)  # Name of the package
    package_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    fragile = models.BooleanField(default=False)  # Whether the package is fragile

    recipient_name = models.CharField(max_length=255, null=True, blank=True)  # Name of the recipient
    recipient_address = models.CharField(max_length=255, null=True, blank=True)  # Address of the recipient
    recipient_lat = models.FloatField()  # Latitude of the recipient
    recipient_long = models.FloatField()  # Longitude of the recipient
    recipient_phone_number = models.CharField(max_length=15, null=True, blank=True)

    pickup_address = models.CharField(max_length=255, null=True, blank=True)  # Pickup location address
    pickup_lat = models.FloatField(default=0)  # Pickup latitude
    pickup_long = models.FloatField(default=0)  # Pickup longitude

    assigned_at = models.DateTimeField(auto_now_add=True)
    sequence = models.PositiveIntegerField()  # Delivery sequence
    completed = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=[("Pending", "Pending"), ("Accepted", "Accepted"), ("Declined", "Declined")],
        default="Pending"
    )

    def __str__(self):
        return f"Rider {self.rider.user.get_full_name if self.rider and hasattr(self.rider.user, 'get_full_name') else 'Unassigned'} for Order {self.order.id}"


class Feedback(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="feedback")
    rating = models.IntegerField()
    comments = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback for Order {self.order.id}"


class SupportTicket(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)

    subject = models.CharField(max_length=255)
    description = models.TextField()
    status = models.CharField(
        max_length=20, choices=[("Open", "Open"), ("Resolved", "Resolved")], default="Open"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Ticket #{self.id} - {self.subject}"
