from rest_framework import serializers
from .models import OrderRiderAssignment


class RiderAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderRiderAssignment
        fields = ['order', 'rider', 'assigned_at', 'status']
