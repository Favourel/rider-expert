from django.urls import path
from .views import (BulkOrderAssignmentView, RealTimeOrderTrackingView, AcceptOrDeclineOrderAssignmentView,
                    BulkOrderSummaryView, FeedbackView, CancelOrderView
                    )


urlpatterns = [
    path('orders/bulk-assign/', BulkOrderAssignmentView.as_view(), name='bulk_order_assign'),

    path('orders/<int:order_id>/tracking/', RealTimeOrderTrackingView.as_view(), name='order_tracking'),
    path('orders/<int:bulk_order_id>/bulk-summary/', BulkOrderSummaryView.as_view(), name='bulk_order_summary'),

    path('orders/accept-decline/', AcceptOrDeclineOrderAssignmentView.as_view(), name='update_assignment_status'),

    path('orders/<int:order_id>/feedback/', FeedbackView.as_view(), name='order_feedback'),
    path('orders/<int:order_id>/cancel/', CancelOrderView.as_view(), name='cancel_order'),

]
