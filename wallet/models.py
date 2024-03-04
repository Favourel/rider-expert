from django.db import models
from accounts.models import CustomUser


class Wallet(models.Model):
    code = models.CharField(max_length=20, unique=True)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    balance = models.DecimalField(default=0, max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WalletTransaction(models.Model):
    TRANSACTION_CHOICES = [
        ("credit", "Credit"),
        ("debit", "Debit"),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
