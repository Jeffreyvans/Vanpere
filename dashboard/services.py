"""Dashboard operations on photos and events (all callers must already have checked ownership)."""
import zipfile

from django.db.models import F
from django.db.models.functions import Greatest

from events.models import Event
from photos.models import Photo
from photos.services.image_pipeline import discard_photo
from storage import get_storage


def set_status(photos, status, reason=""):
    """Approve, reject or restore a queryset of photos; clears any auto-hide flag."""
    return photos.update(status=status, auto_hidden=False,
                         rejected_reason=reason if status == Photo.Status.REJECTED else "")


def delete_photos(event, photos) -> int:
    """Permanently delete photos (files and rows) and release their storage use."""
    rows = list(photos)
    freed = sum(p.total_bytes for p in rows)
    for photo in rows:
        discard_photo(photo)
    if freed:
        Event.objects.filter(pk=event.pk).update(
            storage_used_bytes=Greatest(F("storage_used_bytes") - freed, 0))
    return len(rows)


def set_cover(event, photo) -> None:
    """Copy an approved photo's medium version to be the event cover."""
    storage = get_storage()
    stream = storage.get_stream(photo.key("medium"))
    try:
        data = stream.read()
    finally:
        stream.close()
    event.cover_image = f"events/{event.id}/cover.jpg"
    storage.put(event.cover_image, data, "image/jpeg")
    event.save(update_fields=["cover_image"])


def purge_event_files(event) -> None:
    get_storage().delete_prefix(f"events/{event.id}/")


class _Sink:
    """Write-only buffer that lets zipfile stream without seeking."""

    def __init__(self):
        self.chunks, self.pos = [], 0

    def write(self, data):
        self.chunks.append(bytes(data))
        self.pos += len(data)
        return len(data)

    def tell(self):
        return self.pos

    def flush(self):
        pass

    def drain(self):
        out = b"".join(self.chunks)
        self.chunks.clear()
        return out


def stream_zip(photos, storage):
    """Yield a ZIP of original photos in 64 KB pieces; never holds a whole photo or archive in RAM."""
    sink = _Sink()
    archive = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True)
    for n, photo in enumerate(photos, 1):
        info = zipfile.ZipInfo(f"photo-{n:04d}.jpg", date_time=photo.created_at.timetuple()[:6])
        info.compress_type = zipfile.ZIP_STORED
        source = storage.get_stream(photo.key("original"))
        try:
            with archive.open(info, "w", force_zip64=True) as dest:
                for chunk in iter(lambda: source.read(65536), b""):
                    dest.write(chunk)
                    data = sink.drain()
                    if data:
                        yield data
        finally:
            source.close()
        data = sink.drain()
        if data:
            yield data
    archive.close()
    yield sink.drain()
