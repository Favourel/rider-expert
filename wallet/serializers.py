from rest_framework import serializers
from .models import Wallet


class WalletSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()

    class Meta:
        model = Wallet
        fields = ["user", "balance"]


class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = [
            "amount",
            "transaction_type",
            "transaction_reference",
            "transaction_id",
            "transaction_status",
            "created_at",
            "paid_at",
        ]
