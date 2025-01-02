from django.contrib import admin

from multi_orders.models import OrderRiderAssignment
from .models import DeclinedOrder, Order

# Register your models here.


class OrderRiderAssignmentInline(admin.TabularInline):
    model = OrderRiderAssignment
    extra = 1


class OrderAdmin(admin.ModelAdmin):
    list_display = ['customer', 'rider', 'pickup_address', 'is_bulk', 'recipient_name', 'status', 'updated_at']
    list_filter = ['customer', 'rider', 'status', 'created_at']
    search_fields = ['customer', 'rider']
    inlines = [OrderRiderAssignmentInline]


admin.site.register(Order, OrderAdmin)
admin.site.register(DeclinedOrder)


admin.site.site_header = "Rider Expert Administration"
admin.site.site_title = "Rider Expert Admin Portal"
admin.site.index_title = "Welcome to Your Rider Expert Admin"

