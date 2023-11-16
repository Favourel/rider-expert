from django.urls import path
from .views import *

urlpatterns = [
    path("register_customer/", RegisterCustomerView.as_view(), name="register_customer"),
    path('verify-email/<str:token>/', VerifyEmailView.as_view(), name='verify-email'),

]
