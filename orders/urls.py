from django.urls import path
from .views import *

urlpatterns = [
    path("create/", CreateOrderView.as_view(), name="create-order"),
    path(
        "get-rider/",
        GetAvailableRidersView.as_view(),
        name="available_rider",
    ),
    path("accept/", AcceptOrDeclineOrderView.as_view(), name="accept-order"),
    path("assign/", AssignOrderToRiderView.as_view(), name="assign-order"),
    path("<int:order_id>/", OrderDetailView.as_view(), name="order-detail"),
]
