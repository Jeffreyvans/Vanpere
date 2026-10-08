import secrets
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from . import timeutils

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O/1/I/L
CODE_LENGTH = 8


def generate_public_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class Event(models.Model):
    EVENT_TYPES = [
        ("wedding", "Wedding"), ("birthday", "Birthday"), ("funeral", "Funeral or memorial"),
        ("church", "Church event"), ("corporate", "Corporate function"),
        ("graduation", "Graduation"), ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_code = models.CharField(max_length=CODE_LENGTH, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=150)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default="other")
    event_date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.CharField(max_length=255, blank=True, help_text="Storage key")
    expires_at = models.DateTimeField()
    allow_uploads = models.BooleanField(default=True)
    allow_downloads = models.BooleanField("Let guests download originals", default=False)
    moderation_enabled = models.BooleanField(default=False)
    max_upload_size_mb = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="Maximum size per photo in MB.")
    max_video_size_mb = models.PositiveIntegerField(
        default=500, validators=[MinValueValidator(1)],
        help_text="Maximum size per video in MB.")
    max_photos_per_upload = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(50)])
    view_pin_hash = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    storage_used_bytes = models.PositiveBigIntegerField(default=0)
    expiry_marked_at = models.DateTimeField(null=True, blank=True)
    files_purged_at = models.DateTimeField(null=True, blank=True)
    warned_thresholds = models.CharField(max_length=20, blank=True, help_text="Warning days already emailed, e.g. 7,1")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.public_code:
            code = generate_public_code()
            while Event.objects.filter(public_code=code).exists():
                code = generate_public_code()
            self.public_code = code
        super().save(*args, **kwargs)

    @property
    def public_path(self):
        return reverse("events:public", args=[self.public_code])

    @property
    def public_url(self):
        return settings.SITE_URL.rstrip("/") + self.public_path

    @property
    def is_expired(self):
        return timeutils.is_expired(self.expires_at)

    @property
    def days_remaining(self):
        return timeutils.days_remaining(self.expires_at)

    @property
    def has_pin(self):
        return bool(self.view_pin_hash)

    @property
    def cover_key(self):
        return self.cover_image

    @property
    def photo_count(self):
        """Photos visible to guests (approved)."""
        return self.photos.filter(status="approved").count()

    @property
    def warned_days(self):
        return [int(x) for x in self.warned_thresholds.split(",") if x]

    def set_pin(self, raw):
        self.view_pin_hash = make_password(raw)

    def clear_pin(self):
        self.view_pin_hash = ""

    def check_pin(self, raw):
        return self.has_pin and check_password(raw, self.view_pin_hash)

    def regenerate_code(self):
        """Issue a new public code; the old link and QR code stop working."""
        code = generate_public_code()
        while Event.objects.filter(public_code=code).exists():
            code = generate_public_code()
        self.public_code = code
        self.save(update_fields=["public_code"])
