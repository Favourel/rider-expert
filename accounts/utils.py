from riderexpert.celery import shared_task
from django.utils import timezone
from django.core.mail import send_mail
from smtplib import SMTPException
import pyotp
from django.conf import settings
from .models import UserVerification
from math import radians, sin, cos, sqrt, atan2
import logging
from functools import wraps
import time

logger = logging.getLogger(__name__)


class DistanceCalculator:
    def __init__(self, origin):
        self.origin = origin
        self.origin_long, self.origin_lat = map(float, self.origin.split(","))

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """
        Calculate the distance between two points on the Earth's surface
        using the Haversine formula.

        Parameters:
        lat1, lon1: Latitude and longitude of point 1 (in degrees).
        lat2, lon2: Latitude and longitude of point 2 (in degrees).

        Returns:
        Distance between the two points in kilometers.
        """
        # Convert latitude and longitude from degrees to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        distance = 6371 * c  # Earth radius in kilometers
        return distance

    def destinations_within_radius(self, riders_locations, radius):
        """
        Find riders_locations within a specified radius of the origin.

        Parameters:
        riders_locations: List of dictionaries, each containing 'email' and 'location' keys.
                    'location' is a str containing 'longitude,latitude'.
        radius: Radius in kilometers.

        Returns:
        List of dictionaries for riders_locations within the specified radius of the origin.
        """
        within_radius = []
        for location in riders_locations:
            lon, lat = map(float, location["location"].split(","))
            distance = self.haversine_distance(
                self.origin_lat, self.origin_long, lat, lon
            )
            if distance <= radius:
                within_radius.append(
                    {
                        "email": location["email"],
                        "location": "{},{}".format(lon, lat),
                    }
                )
        return within_radius


def retry(ExceptionToCheck=Exception, tries=3, delay=1, backoff=2, logger=None):
    """
    Retry decorator with exponential backoff.
    :param ExceptionToCheck: the exception to check. may be a tuple of exceptions to check
    :param tries: number of times to try (not retry) before giving up
    :param delay: initial delay between retries in seconds
    :param backoff: backoff multiplier e.g. value of 2 will double the delay each retry
    :param logger: logger to use. If None, print
    """

    def deco_retry(f):
        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"{str(e)}, Retrying in {mdelay} seconds..."
                    if logger:
                        logger.warning(msg)
                    else:
                        print(msg)
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)

        return f_retry  # true decorator

    return deco_retry


def generate_otp(length=6):
    """
    Generate a time-based OTP with the specified length.

    Args:
        length (int): The length of the OTP code (default is 6).

    Returns:
        str: The generated OTP code.
    """
    if length not in [4, 6]:
        raise ValueError("OTP length must be either 4 or 6")

    # Generate a time-based OTP using PyOTP
    totp = pyotp.TOTP(pyotp.random_base32())
    otp_value = totp.now()

    # Trim the OTP value to the specified length
    otp_value = otp_value[:length]

    return otp_value



@shared_task
def send_verification_email(user, purpose=None):
    otp_code = generate_otp()
    current_site = "myAuth.com"

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
    else:
        subject = "One time passcode for Email verification"
        email_body = "Hi {} you requested to resend the verification email on {} \nplease verify your email with the one time code {}".format(
            user.first_name, current_site, otp_code
        )

    email = user.email
    from_email = settings.DEFAULT_FROM_EMAIL

    try:
        send_mail(subject, email_body, from_email, [email], fail_silently=False)
    except SMTPException:
        logger.error("Email could not be sent.")

    # Save the OTP in the OTP model
    time_now = timezone.now()
    UserVerification.objects.get_or_create(
        user=user,
        otp=otp_code,
        created_at=time_now,
        otp_expiration_time=time_now + timezone.timedelta(minutes=30),
    )

def str_to_bool(s):
    return s.lower() in ["true", "1", "yes", "on"]
