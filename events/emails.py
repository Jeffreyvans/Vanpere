from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from django.conf import settings
from django.urls import reverse


def send_event_created(event):
    """Branded confirmation with the guest link."""
    ctx = {"event": event, "manage_url": settings.SITE_URL.rstrip("/") + reverse("events:detail", args=[event.pk])}
    msg = EmailMultiAlternatives(
        f"Your VanPere Digital event is live: {event.name}",
        render_to_string("emails/event_created.txt", ctx), to=[event.owner.email])
    msg.attach_alternative(render_to_string("emails/event_created.html", ctx), "text/html")
    msg.send()


def send_expiry_warning(event, days):
    """Tell the organiser the event expires soon (HTML + plain text)."""
    ctx = {"event": event, "days": days,
           "manage_url": settings.SITE_URL.rstrip("/") + reverse("dashboard:event", args=[event.pk])}
    msg = EmailMultiAlternatives(
        f"{event.name} expires in {days} day{'s' if days != 1 else ''} | VanPere Digital",
        render_to_string("emails/expiry_warning.txt", ctx), to=[event.owner.email])
    msg.attach_alternative(render_to_string("emails/expiry_warning.html", ctx), "text/html")
    msg.send()
