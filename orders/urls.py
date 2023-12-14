from . import assign_order_to_rider
from django.urls import path


urlpatterns = [
    path('/api/orders/<int:order_id>/rider/<rider_id>/', assign_order_to_rider, name='assign-order-to-rider'),
]
