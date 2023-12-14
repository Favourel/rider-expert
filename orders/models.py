from django.db import models
from accounts.models import Customer, Rider

# Create your models here.
class Order(models.Model):
    STATUS_CHOICES = [
        ('PendingPickup', 'Pending Pickup'),
        ('WaitingForPickup', 'Waiting for pickup'),
        ('PickedUp', 'Picked up'),
        ('InTransit', 'In transit'),
        ('Arrived', 'Arrived'),
        ('Delivered', 'Delivered'),
        ('Failed', 'Failed'),
    ]
    
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    rider = models.ForeignKey(Rider, on_delete=models.CASCADE, default=None)
    pickup_address = models.TextField()
    order_number = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    recipients_name = models.CharField(max_length=100)
    recipient_address = models.TextField()
    recipient_phone_number = models.CharField(max_length=15)
    order_completion_code = models.CharField(max_length=10)
    parcel_weight = models.DecimalField(max_digits=5, decimal_places=2)
    parcel_value = models.DecimalField(max_digits=10, decimal_places=2)
    fragile = models.BooleanField(default=False)    
    
    def __str__(self):
        return self.order_number