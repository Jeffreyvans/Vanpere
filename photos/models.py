import uuid

from django.db import models


class Photo(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="photos")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADING)
    uploader_hash = models.CharField(max_length=64, db_index=True)
    ip_hash = models.CharField(max_length=64)
    uploader_name = models.CharField(max_length=60, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    batch_id = models.UUIDField(null=True, blank=True)
    declared_content_type = models.CharField(max_length=30)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    original_bytes = models.PositiveBigIntegerField(default=0)
    medium_bytes = models.PositiveBigIntegerField(default=0)
    thumb_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.CharField(max_length=200, blank=True)
    auto_hidden = models.BooleanField(default=False, help_text="Hidden automatically after too many reports")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event", "status", "created_at"]),
            models.Index(fields=["event", "content_hash"]),
        ]
        constraints = [models.UniqueConstraint(
            fields=["event", "content_hash"], condition=~models.Q(content_hash=""),
            name="uniq_event_content_hash")]

    @property
    def prefix(self):
        return f"events/{self.event_id}/{self.id}"

    @property
    def upload_key(self):
        return f"{self.prefix}/upload.bin"

    def key(self, version):
        """Storage key for 'original', 'medium' or 'thumb'."""
        return f"{self.prefix}/{version}.jpg"

    @property
    def total_bytes(self):
        return self.original_bytes + self.medium_bytes + self.thumb_bytes


class UploadConsent(models.Model):
    """Recorded once per device and event; stores a hash of the IP, never the raw IP."""
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="consents")
    device_hash = models.CharField(max_length=64)
    ip_hash = models.CharField(max_length=64)
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "device_hash"], name="uniq_consent_device")]


class Report(models.Model):
    """A guest report of a photo; one per device and photo."""
    class Reason(models.TextChoices):
        INAPPROPRIATE = "inappropriate", "Inappropriate or offensive"
        PRIVACY = "privacy", "Privacy concern"
        SPAM = "spam", "Spam or unrelated"
        OTHER = "other", "Something else"

    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    note = models.CharField(max_length=300, blank=True)
    reporter_hash = models.CharField(max_length=64)
    dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["photo", "reporter_hash"], name="uniq_report_device")]
