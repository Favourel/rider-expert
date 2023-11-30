from django.utils import timezone
from django.core.mail import send_mail
from smtplib import SMTPException
from rest_framework import serializers
import pyotp
from django.conf import settings
from .models import UserVerification


def generate_otp():
    # Generate a time-based OTP using PyOTP
    totp = pyotp.TOTP(pyotp.random_base32())
    otp_value = totp.now()
    return otp_value


def send_verification_email(user, purpose):
    if purpose == "registration":
        subject = "One time passcode for Email verification"
        email_body = "Hi {} thanks for signing up on {} \nplease verify your email with the one time code {}".format(
            user.first_name, current_site, otp_code
        )
    elif purpose == "forgot_password":
        subject = "Reset your password"
        email_body = "Hi {} you requested a password reset on {} \nplease reset your password with the one-time code {}".format(
            user.first_name, current_site, otp_code
        )
    otp_code = generate_otp()
    email = user.email
    current_site = "myAuth.com"
    from_email = settings.DEFAULT_FROM_EMAIL

    try:
        send_mail(subject, email_body, from_email, [email], fail_silently=False)
    except SMTPException:
        raise serializers.ValidationError("Email could not be sent.")

    # Save the OTP in the OTP model
    otp_instance, created = UserVerification.objects.get_or_create(user=user)
    otp_instance.otp = otp_code
    otp_instance.created_at = timezone.now()
    otp_instance.otp_expiration_time = timezone.now() + timezone.timedelta(minutes=30)
    otp_instance.save()
