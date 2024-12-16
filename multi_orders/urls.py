from django.urls import path
from .views import (BulkOrderAssignmentView, RealTimeOrderTrackingView, AcceptOrDeclineOrderAssignmentView,
                    BulkOrderSummaryView, FeedbackView, CancelOrderView, UpdateBulkOrderStatusView
                    )


urlpatterns = [
    path('accept-decline/', AcceptOrDeclineOrderAssignmentView.as_view(), name='update_assignment_status'),

    path('bulk-assign/', BulkOrderAssignmentView.as_view(), name='bulk_order_assign'),

    path('update-order-status/', UpdateBulkOrderStatusView.as_view(), name='bulk_order_assign'),

    path('<int:order_id>/tracking/', RealTimeOrderTrackingView.as_view(), name='order_tracking'),
    path('<int:order_id>/bulk-summary/', BulkOrderSummaryView.as_view(), name='bulk_order_summary'),

    path('<int:order_id>/feedback/', FeedbackView.as_view(), name='order_feedback'),
    path('<int:order_id>/cancel/', CancelOrderView.as_view(), name='cancel_order'),

]
