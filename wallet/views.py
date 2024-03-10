from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import WalletTransaction
from .serializers import WalletSerializer, WalletTransactionSerializer


class GetWalletBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        wallet = request.user.wallet
        wallet_serializer = WalletSerializer(wallet)
        transactions = WalletTransaction.objects.filter(wallet=wallet)
        transactions_serializer = WalletTransactionSerializer(transactions, many=True)
        return Response(
            {
                "message": {
                    "Balance ": wallet_serializer.data,
                    "Transactions ": transactions_serializer.data,
                }
            },
            status=status.HTTP_200_OK,
        )


class DebitWalletBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        wallet = request.user.wallet
        amount = request.data.get("amount")

        wallet_balance = wallet.balance

        if wallet_balance < amount:
            return Response(
                {"error": "Insufficient balance"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wallet.balance -= amount
        wallet.updated_at = timezone.now()
        wallet.save()

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type="Debit",
            amount=amount,
            created_at=timezone.now(),
        )

        return Response(
            {"message": "Balance debited successfully"}, status=status.HTTP_200_OK
        )
