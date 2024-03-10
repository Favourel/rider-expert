import hmac
import hashlib
import json
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.models import CustomUser
from wallet.models import WalletTransaction, Wallet

logger = logging.getLogger(__name__)
secret = settings.PAYSTACK_SECRET_KEY


class PaystackWebhookView(APIView):
    @csrf_exempt
    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.headers.get("x-paystack-signature")
        body = None
        event = None

        try:
            hash = hmac.new(
                secret.encode("utf-8"), payload, digestmod=hashlib.sha512
            ).hexdigest()
            if hash != sig_header:
                raise Exception("Invalid signature")

            body = json.loads(payload.decode("utf-8"))
            event = body.get("event")
        except (ValueError, KeyError, Exception) as e:
            logger.error(f"Error processing webhook: {e}")
            return Response({"error": "Invalid request"}, status=400)

        data = body.get("data")
        customer = data.get("customer")

        if event == "charge.success":
            try:
                with transaction.atomic():
                    user = CustomUser.objects.filter(
                        email=customer.get("email")
                    ).first()
                    wallet, created = Wallet.objects.get_or_create(
                        user=user,
                        code=customer.get("customer_code"),
                        created_at=data.get("created_at"),
                    )
                    WalletTransaction.objects.create(
                        wallet=wallet,
                        amount=data.get("amount"),
                        transaction_reference=data.get("reference"),
                        transaction_id=data.get("id"),
                        transaction_status=data.get("status"),
                        transaction_type="Credit",
                        created_at=data.get("created_at"),
                        paid_at=data.get("paid_at"),
                    )

                    wallet.balance += data.get("amount")
                    wallet.updated_at = data.get("paid_at")
                    wallet.save()
                return Response(
                    {"message": "Webhook processed successfully"}, status=200
                )
            except CustomUser.DoesNotExist:
                return Response({"error": "User not found"}, status=404)
            except Wallet.DoesNotExist:
                return Response({"error": "Wallet not found"}, status=404)
            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                return Response({"error": "An error occurred"}, status=500)
        else:
            try:
                bank_transfer = data.get("bank_transfer")
                WalletTransaction.objects.create(
                    amount=data.get("amount") or bank_transfer.get("amount"),
                    transaction_reference=data.get("reference"),
                    transaction_id=data.get("id") or bank_transfer.get("id"),
                    transaction_status=data.get("status") or "failed",
                    created_at=data.get("created_at") or timezone.now(),
                )
                return Response({"message": bank_transfer.get("message")}, status=400)
            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                return Response({"error": "An error occurred"}, status=500)
