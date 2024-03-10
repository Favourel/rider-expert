from django.db import models
from accounts.models import CustomUser


class Wallet(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    code = models.CharField(max_length=20, unique=True)
    balance = models.DecimalField(default=0, max_digits=12, decimal_places=2)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()


class WalletTransaction(models.Model):
    TRANSACTION_CHOICES = [
        ("credit", "Credit"),
        ("debit", "Debit"),
    ]
    TRANSACTION_STATUS = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE)
    transaction_type = models.CharField(
        max_length=25, choices=TRANSACTION_CHOICES, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_reference = models.CharField(
        max_length=20, unique=True, null=True, blank=True
    )
    transaction_id = models.BigIntegerField(null=True, blank=True, unique=True)
    transaction_status = models.CharField(
        max_length=30, choices=TRANSACTION_STATUS, default="pending"
    )
    created_at = models.DateTimeField()
    paid_at = models.DateTimeField()


class PendingWalletTransaction(models.Model):
    TRANSACTION_STATUSES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("refunded", "Refunded"),
    ]
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_status = models.CharField(
        max_length=30, choices=TRANSACTION_STATUSES, default="pending"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
