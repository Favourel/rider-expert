from django.utils import timezone
from django.core.mail import send_mail
from smtplib import SMTPException
from rest_framework import serializers
import pyotp
from django.conf import settings
from .models import UserVerification


def generate_otp(user):
    # Generate a time-based OTP using PyOTP
    totp = pyotp.TOTP(pyotp.random_base32())
    otp_value = totp.now()

    # Save the OTP in the OTP model
    otp_instance, created = UserVerification.objects.get_or_create(user=user)
    otp_instance.email_otp = otp_value
    otp_instance.created_at = timezone.now()
    otp_instance.email_expiration_time = timezone.now() + timezone.timedelta(minutes=30)
    otp_instance.save()

    return otp_value


def send_verification_email(user):
    subject = "One time passcode for Email verification"
    otp_code = generate_otp(user)
    email = user.user_id.email
    current_site = "myAuth.com"
    email_body = "Hi {} thanks for signing up on {} \nplease verify your email with the one time code {}".format(
        user.user_id.first_name, current_site, otp_code
    )
    from_email = settings.DEFAULT_FROM_EMAIL

    try:
        send_mail(subject, email_body, from_email, [email], fail_silently=False)
    except SMTPException:
        raise serializers.ValidationError("Email could not be sent.")
