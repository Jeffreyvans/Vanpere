import uuid

from django.db import models

IMAGE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
             "image/heic": "heic", "image/heif": "heif", "image/mpo": "jpg"}
VIDEO_EXT = {"video/mp4": "mp4", "video/quicktime": "mov", "video/x-m4v": "m4v",
             "video/webm": "webm", "video/3gpp": "3gp", "video/3gp": "3gp"}
VIDEO_EXT_FALLBACK = ("mp4", "mov", "webm", "m4v", "3gp", "mkv")
VIDEO_CONTENT_TYPES = {
    "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
    "m4v": "video/m4v", "3gp": "video/3gpp", "mkv": "video/x-matroska"}


def media_ext_from(content_type, fallback="jpg") -> str:
    return IMAGE_EXT.get(content_type, VIDEO_EXT.get(content_type, fallback or "bin"))


class Photo(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="photos")
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADING)
    uploader_hash = models.CharField(max_length=64, db_index=True)
    ip_hash = models.CharField(max_length=64)
    uploader_name = models.CharField(max_length=60, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    batch_id = models.UUIDField(null=True, blank=True)
    declared_content_type = models.CharField(max_length=30, default="image/jpeg")
    original_ext = models.CharField(max_length=8, blank=True, help_text="Extension of the stored original")
    upload_id = models.CharField(max_length=180, blank=True, help_text="S3 multipart upload id, if any")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    original_bytes = models.PositiveBigIntegerField(default=0)
    medium_bytes = models.PositiveBigIntegerField(default=0)
    thumb_bytes = models.PositiveBigIntegerField(default=0)
    poster_bytes = models.PositiveBigIntegerField(default=0)
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
    def is_video(self):
        return self.media_type == self.MediaType.VIDEO

    @property
    def upload_key(self):
        return f"{self.prefix}/upload.bin"

    @property
    def original_extension(self):
        if self.original_ext:
            return self.original_ext
        ext = media_ext_from(self.declared_content_type, "")
        if not ext and self.is_video:
            ext = "mp4"
        return ext or "jpg"

    def key(self, version):
        """Storage key for 'original', 'medium', 'thumb' or 'poster'."""
        ext = {"original": self.original_extension, "medium": "webp",
               "thumb": "webp", "poster": "webp"}[version]
        return f"{self.prefix}/{version}.{ext}"

    @property
    def original_content_type(self):
        return self.declared_content_type or "application/octet-stream"

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


class Comment(models.Model):
    """A plain-text guest comment on an approved photo; the author is the device."""
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="comments")
    actor_hash = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=40, blank=True)
    body = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["photo", "created_at"], name="photos_comment_photo_created")]

    def __str__(self):
        return self.body[:40]


class Like(models.Model):
    """A guest like on a photo; one per device and photo."""
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="likes")
    actor_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["photo", "actor_hash"], name="uniq_like_photo_device")]
