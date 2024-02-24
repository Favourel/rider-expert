from django.urls import path
from .views import *

urlpatterns = [
    path("create/", CreateOrder.as_view(), name="create-order"),
    path("order/<int:order_id>/", OrderDetailView.as_view(), name="order-detail"),
    path("accept/", AcceptOrderView.as_view(), name="accept-order"),
]
