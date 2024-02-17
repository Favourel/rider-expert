from django.urls import path
from .views import OrderCreateView

urlpatterns = [
    path('api/orders/', OrderCreateView.as_view(), name='order-create'),
]
