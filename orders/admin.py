from django.contrib import admin
from .models import DeclinedOrder, Order

# Register your models here.
admin.site.register(Order)
admin.site.register(DeclinedOrder)


admin.site.site_header = "Rider Expert Administration"
admin.site.site_title = "Rider Expert Admin Portal"
admin.site.index_title = "Welcome to Your Rider Expert Admin"

