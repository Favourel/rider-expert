from django.utils import timezone
from django.db import transaction
from orders.models import Order
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from .models import PendingWalletTransaction, WalletTransaction
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
                **wallet_serializer.data,
                "transactions": transactions_serializer.data,
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
            transaction_type="debit",
            amount=amount,
            created_at=timezone.now(),
        )

        return Response(
            {"message": "Balance debited successfully"}, status=status.HTTP_200_OK
        )


class CreditRiderWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        wallet = request.user.wallet
        order_id = request.data.get("order_id")

        try:
            order = Order.objects.get(
                id=order_id, rider=wallet.user, status="Delivered"
            )
        except Order.DoesNotExist:
            return Response(
                {"error": "Order not found or not delivered."},
                status=status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            amount = order.price
            wallet.balance += amount
            wallet.updated_at = timezone.now()
            wallet.save()

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="credit",
                amount=amount,
                created_at=timezone.now(),
            )

            PendingWalletTransaction.objects.filter(order=order).update(
                transaction_status="completed"
            )

        return Response(
            {"message": "Balance credited successfully"}, status=status.HTTP_200_OK
        )
