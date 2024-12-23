from django.db import models
from orders.models import Order
from accounts.models import Rider, Customer


# Create your models here.


class OrderRiderAssignment(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, null=True, blank=True)

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="assignments")
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, related_name="assignments")

    assigned_weight = models.DecimalField(max_digits=10, decimal_places=2)
    assigned_at = models.DateTimeField(auto_now_add=True)

    recipient_lat = models.FloatField()
    recipient_long = models.FloatField()
    destination = models.CharField(max_length=255)  # Latitude and longitude combined

    sequence = models.PositiveIntegerField()  # Delivery sequence
    fragile = models.BooleanField(default=False)

    completed = models.BooleanField(default=False)

    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=[("Pending", "Pending"), ("Accepted", "Accepted"), ("Declined", "Declined")],
        default="Pending"
    )

    def __str__(self):
        return f"Rider {self.rider.user.get_full_name()} for Order {self.order.id}"


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
