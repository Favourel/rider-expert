from django.http import Http404
from django.db import DatabaseError
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Customer
from .serializers import CustomerSerializer


class RegisterCustomerView(APIView):
    """
    API view to handle user registration.
    """
    def post(self, request):
        """
        Handle POST requests. Validate the request data using the CustomerSerializer,
        create a new user if the data is valid, and return a response with the user data
        or validation errors.
        """
        serializer = CustomerSerializer(data=request.data)
        if serializer.is_valid():
            try:
                user = serializer.save()
                if user:
                    return Response(serializer.data, status=status.HTTP_201_CREATED)
            except DatabaseError:
                return Response({"detail": "Database error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyEmailView(APIView):
    """
    API view to handle email verification.
    """
    def get(self, request):
        """
        Handle GET requests. Validate the verification token, mark the user's email as
        verified if the token is valid, and return a response with a success message or
        error message.
        """
        token = request.query_params.get("token", None)
        if token:
            try:
                customer = get_object_or_404(Customer, verification_token=token)
            except Http404:
                return Response(
                    {"detail": "Invalid or expired verification link."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Check if the token has expired
            if customer.verification_token_expires < timezone.now():
                return Response(
                    {"detail": "Verification link has expired."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Mark the email as verified and remove the token
            customer.is_email_verified = True
            customer.verification_token = None
            customer.verification_token_expires = None
            customer.save()

            return Response(
                {"detail": "Email successfully verified."}, status=status.HTTP_200_OK
            )
        return Response(
            {"detail": "Invalid or expired verification link."},
            status=status.HTTP_400_BAD_REQUEST,
        )
