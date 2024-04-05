from django.urls import path
from . import views

urlpatterns = [
    path("create/", views.CreateOrderView.as_view(), name="create-order"),
    path(
        "get-rider/",
        views.GetAvailableRidersView.as_view(),
        name="available_rider",
    ),
    path("accept/", views.AcceptOrDeclineOrderView.as_view(), name="accept-order"),
    path("assign/", views.AssignOrderToRiderView.as_view(), name="assign-order"),
    path("<int:order_id>/", views.OrderDetailView.as_view(), name="order-detail"),
    path(
        "current/<email>/",
        views.GetOrderDetailByUser.as_view(),
        name="order-detail-by-user",
    ),
    path(
        "update-order-status/",
        views.UpdateOrderStatusView.as_view(),
        name="update-order-status",
    ),
]
