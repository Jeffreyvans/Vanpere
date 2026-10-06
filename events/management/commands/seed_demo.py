import io
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw, ImageOps

from accounts.models import User
from events import timeutils
from events.models import Event
from photos.models import Photo
from photos.security import digest
from photos.services.image_pipeline import process_photo
from storage import get_storage

DEMO_NAME = "Tendai & Rudo Wedding (demo)"
GUESTS = ["Ann", "Tapiwa", "Rudo", ""]
PALETTE = [((27, 26, 46), (201, 162, 75)), ((120, 40, 60), (250, 220, 200)), ((20, 90, 80), (200, 240, 220)),
           ((60, 60, 120), (220, 200, 250)), ((140, 80, 20), (250, 235, 190)), ((30, 30, 30), (230, 230, 230)),
           ((10, 80, 140), (190, 225, 250)), ((100, 20, 100), (250, 200, 240))]
SIZES = [(1600, 1200), (1200, 1600), (1600, 900), (1200, 1200)]


def sample_image(i):
    dark, light = PALETTE[i % len(PALETTE)]
    w, h = SIZES[i % len(SIZES)]
    img = ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), dark, light)
    draw = ImageDraw.Draw(img)
    r = min(w, h) // 4
    cx, cy = w // 2, h // 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=light, width=max(6, r // 12))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Create a demo organiser and event with sample photos (development only; safe to re-run)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@example.com")
        parser.add_argument("--password", default="demo-pass-12345")
        parser.add_argument("--force", action="store_true", help="Allow when DEBUG is off.")

    def handle(self, *args, **o):
        if not settings.DEBUG and not o["force"]:
            raise CommandError("seed_demo creates a user with a known password. Run it in development "
                               "or pass --force if you really mean it.")
        user, created = User.objects.get_or_create(
            email=o["email"].lower(),
            defaults={"full_name": "Demo Organiser", "email_verified": True, "is_staff": True, "is_superuser": True})
        if created:
            user.set_password(o["password"])
            user.save()
        elif not (user.is_staff and user.is_superuser and user.email_verified):
            user.is_staff = user.is_superuser = user.email_verified = True
            user.save(update_fields=["is_staff", "is_superuser", "email_verified"])
        event = Event.objects.filter(owner=user, name=DEMO_NAME).first()
        if event is None:
            day = timeutils.local_today() + timedelta(days=7)
            event = Event.objects.create(
                owner=user, name=DEMO_NAME, event_type="wedding", event_date=day, location="Harare",
                description="Demo event created by seed_demo.", expires_at=timeutils.default_expires_at(day))
        if not event.photos.exists():
            storage = get_storage()
            for i in range(8):
                photo = Photo.objects.create(
                    event=event, uploader_hash=digest(f"dev:demo-guest-{i % 3}"), ip_hash=digest("ip:seed"),
                    uploader_name=GUESTS[i % len(GUESTS)], declared_content_type="image/jpeg")
                storage.put(photo.upload_key, sample_image(i), "image/jpeg")
                process_photo(photo.id)
        self.stdout.write(self.style.SUCCESS(
            f"Demo ready.\n  Guest link: {event.public_url}\n  Organiser login: {user.email}"
            + (" (password set for new account; not printed)" if created else " (existing account, password unchanged)")))
