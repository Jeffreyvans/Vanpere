"""Image pipeline. `process_photo` is a pure function of a photo id.

Background-worker hook: it runs synchronously from the finalise endpoint today; to move it
to Celery/RQ, enqueue `process_photo(photo_id)` there instead (no other change needed).
"""
import hashlib

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from events.models import Event
from photos.models import Photo
from storage import get_storage

from .imaging import PhotoRejected, build_versions

__all__ = ["process_photo", "discard_photo", "PhotoRejected", "DuplicatePhoto"]


class DuplicatePhoto(Exception):
    """The same content already exists for this event."""


def discard_photo(photo: Photo) -> None:
    """Remove every stored object and the database row of a photo."""
    get_storage().delete_prefix(photo.prefix)
    photo.delete()


def process_photo(photo_id) -> Photo:
    """Validate, strip metadata, create original/medium/thumb, record sizes and storage use.

    Raises PhotoRejected or DuplicatePhoto (callers discard the photo). Idempotent once processed.
    """
    photo = Photo.objects.select_related("event").get(pk=photo_id)
    if photo.status != Photo.Status.UPLOADING:
        return photo
    storage, event = get_storage(), photo.event
    limit = event.max_upload_size_mb * 1024 * 1024
    stream = storage.get_stream(photo.upload_key)
    try:
        raw = stream.read(limit + 1)
    finally:
        stream.close()
    if len(raw) > limit:
        raise PhotoRejected("File is larger than this event allows.")

    versions = build_versions(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if Photo.objects.filter(event=event, content_hash=digest).exclude(pk=photo.pk).exists():
        raise DuplicatePhoto()

    for name in ("original", "medium", "thumb"):
        storage.put(photo.key(name), versions[name], "image/jpeg")
    photo.content_hash = digest
    photo.width, photo.height = versions["size"]
    photo.original_bytes = len(versions["original"])
    photo.medium_bytes = len(versions["medium"])
    photo.thumb_bytes = len(versions["thumb"])
    photo.status = Photo.Status.PENDING if event.moderation_enabled else Photo.Status.APPROVED
    photo.finalised_at = timezone.now()
    try:
        with transaction.atomic():
            photo.save()
            Event.objects.filter(pk=event.pk).update(
                storage_used_bytes=F("storage_used_bytes") + photo.total_bytes)
    except IntegrityError:
        raise DuplicatePhoto()
    storage.delete(photo.upload_key)
    return photo
