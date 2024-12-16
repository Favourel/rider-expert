from django.contrib import admin
from .models import Wallet, WalletTransaction, PendingWalletTransaction


# Register your models here.
admin.site.register(Wallet)
admin.site.register(WalletTransaction)
admin.site.register(PendingWalletTransaction)
