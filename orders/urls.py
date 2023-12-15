from django.urls import path
from .views import OrderCreateView, OrderDetailView

urlpatterns = [
    path('api/orders/', OrderCreateView.as_view(), name='order-create'),
    path('api/orders/<int:order_id>/',
         OrderDetailView.as_view(), name='order-detail'),
]
