"""Branded VanPere Digital emails (HTML + plain text)."""
from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

VERIFY_SALT = "verify-email"


def send_verification_email(user):
    """Send a signed, expiring verification link to the organiser."""
    token = signing.dumps({"uid": user.pk, "e": user.email}, salt=VERIFY_SALT)
    ctx = {
        "user": user,
        "verify_url": settings.SITE_URL + reverse("accounts:verify", args=[token]),
        "hours": settings.EMAIL_VERIFY_MAX_AGE // 3600,
    }
    msg = EmailMultiAlternatives(
        "Verify your email for VanPere Digital",
        render_to_string("emails/verify.txt", ctx),
        to=[user.email],
    )
    msg.attach_alternative(render_to_string("emails/verify.html", ctx), "text/html")
    msg.send()
