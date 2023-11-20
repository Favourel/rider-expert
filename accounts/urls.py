# urls.py

from django.urls import path
from .views import RiderRegistrationView

urlpatterns = [
    path('riders/register/', RiderRegistrationView.as_view(), name='rider-registration'),
]
