from rest_framework import serializers
from .models import Wallet


class WalletSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()

    class Meta:
        model = Wallet
        fields = ["user", "balance"]
