from django.urls import path
from .views import *

urlpatterns = [
    path("create-order/", OrderCreateView.as_view(), name="create-order"),
    path("order/<int:order_id>/", OrderDetailView.as_view(), name="order-detail"),
    path("accept-order/", AcceptOrderView.as_view(), name="accept-order"),
]
