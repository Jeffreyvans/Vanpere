"""Media pipeline. `process_photo` runs from the finalise endpoint (photo id in, photo out).

Images: the original object is copied byte-for-byte (never re-encoded, never altered),
then decoded from a temp file on disk and WebP thumb/preview are derived. The whole
original is never loaded into memory; only the decoded pixels are.

Videos: no server-side processing (there is no ffmpeg dependency). The original is
copy-stored as-is; the poster frame is captured client-side and attached via the
poster endpoint.
"""
import logging
import os
import tempfile

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from events.models import Event
from photos.models import Photo
from storage import get_storage

from .imaging import PhotoRejected, build_versions, file_sha256

__all__ = ["process_photo", "discard_photo", "PhotoRejected", "DuplicatePhoto"]

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


class DuplicatePhoto(Exception):
    """The same content already exists for this event."""


def discard_photo(photo: Photo) -> None:
    """Remove every stored object and the database row of a photo."""
    storage = get_storage()
    if photo.upload_id:
        try:
            storage.abort_multipart(photo.upload_key, photo.upload_id)
        except Exception:
            logger.exception("abort_multipart failed for %s", photo.upload_key)
    storage.delete_prefix(photo.prefix)
    photo.delete()


def _mark(storage, photo, thumb, preview, size, digest, original_bytes):
    event = photo.event
    storage.copy(photo.upload_key, photo.key("original"))
    storage.put(photo.key("medium"), preview, "image/webp")
    storage.put(photo.key("thumb"), thumb, "image/webp")
    photo.content_hash = digest
    photo.original_ext = photo.original_extension
    photo.width, photo.height = size
    photo.original_bytes = original_bytes
    photo.medium_bytes = len(preview)
    photo.thumb_bytes = len(thumb)
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


def _process_image(photo: Photo) -> Photo:
    storage, event = get_storage(), photo.event
    limit = min(event.max_upload_size_mb, settings.MAX_IMAGE_UPLOAD_MB) * 1024 * 1024
    stream = storage.get_stream(photo.upload_key)
    fd, tmp = tempfile.mkstemp(prefix="vanpere-img-")
    os.close(fd)
    size = 0
    try:
        try:
            with open(tmp, "wb") as out:
                while True:
                    data = stream.read(_CHUNK)
                    if not data:
                        break
                    size += len(data)
                    if size > limit:
                        raise PhotoRejected("File is larger than this event allows.")
                    out.write(data)
            if size == 0:
                raise PhotoRejected("The uploaded file is empty.")
            digest = file_sha256(tmp)
            if Photo.objects.filter(event=event, content_hash=digest).exclude(pk=photo.pk).exists():
                raise DuplicatePhoto()
            versions = build_versions(tmp, settings.THUMB_EDGE, settings.PREVIEW_EDGE)
        finally:
            try:
                stream.close()
            except Exception:
                pass
        _mark(storage, photo, versions["thumb"], versions["preview"], versions["size"], digest, size)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return photo


def _process_video(photo: Photo) -> Photo:
    storage, event = get_storage(), photo.event
    limit = min(event.max_video_size_mb, settings.MAX_VIDEO_UPLOAD_MB) * 1024 * 1024
    size = storage.size(photo.upload_key)
    if size <= 0 or size > limit:
        raise PhotoRejected("File is larger than this event allows.")
    storage.copy(photo.upload_key, photo.key("original"))
    photo.original_ext = photo.original_extension
    photo.original_bytes = size
    photo.medium_bytes = photo.thumb_bytes = 0
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


def process_photo(photo_id) -> Photo:
    """Validate, store the original untouched, derive WebP versions, record sizes.

    Raises PhotoRejected or DuplicatePhoto (callers discard the photo). Idempotent once processed.
    """
    photo = Photo.objects.select_related("event").get(pk=photo_id)
    if photo.status != Photo.Status.UPLOADING:
        return photo
    if photo.is_video:
        return _process_video(photo)
    return _process_image(photo)