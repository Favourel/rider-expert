from django.contrib import admin
from .models import DeclinedOrder, Order

# Register your models here.
admin.site.register(Order)
admin.site.register(DeclinedOrder)
