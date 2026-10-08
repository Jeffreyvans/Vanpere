"""Guest upload API: consent, duplicate check, init, parts, server fallback, poster, finalise.

Large images and all videos upload directly to object storage (single presigned PUT for
images, S3 multipart for videos) so the container never buffers a 100+ MB file. The server
closed-loop endpoints only hand out cursors; the fallback `upload_file` path is a degraded
route used when direct uploads are unavailable.
"""
import hmac
import os
import re
import tempfile
import uuid

from django.conf import settings
from django.db import IntegrityError
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from events.models import Event
from storage import get_storage

from . import ratelimit
from .models import Photo, UploadConsent
from .security import device_hash, device_token, digest, ip_hash
from .services.image_pipeline import DuplicatePhoto, PhotoRejected, discard_photo, process_photo
from .services.imaging import encode_webp, open_validated_path
from accounts.utils import client_ip

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/m4v",
               "video/x-m4v", "video/3gpp", "video/3gp"}
ALLOWED_TYPES = IMAGE_TYPES | VIDEO_TYPES
VISIBLE = (Photo.Status.PENDING, Photo.Status.APPROVED, Photo.Status.REJECTED)


def err(code, status, **extra):
    return Response({"error": code, **extra}, status=status)


def guest_api(parsers=(JSONParser,), methods=("POST",)):
    """Anonymous POST endpoint; authority is the device token header, so no CSRF/session auth."""
    def deco(fn):
        fn = parser_classes(list(parsers))(fn)
        fn = permission_classes([AllowAny])(fn)
        fn = authentication_classes([])(fn)
        return api_view(list(methods))(fn)
    return deco


def _context(request, code, uploading=True):
    event = Event.objects.filter(public_code=code.upper(), is_active=True).first()
    if event is None:
        return None, None, err("not_found", 404)
    token = device_token(request)
    if not token:
        return None, None, err("device_token_required", 400)
    if uploading and event.is_expired:
        return None, None, err("event_ended", 410)
    if uploading and not event.allow_uploads:
        return None, None, err("uploads_disabled", 403)
    return event, token, None


def _throttled(request, token, scope, factor=1):
    ok_dev = ratelimit.hit(f"{scope}:dev", digest(token), settings.UPLOAD_RATE_PER_DEVICE * factor)
    ok_ip = ratelimit.hit(f"{scope}:ip", digest(client_ip(request)), settings.UPLOAD_RATE_PER_IP * factor)
    return None if (ok_dev and ok_ip) else err("rate_limited", 429)


def _own_photo(event, token, photo_id):
    photo = Photo.objects.filter(pk=photo_id, event=event).first()
    if photo is None:
        return None, err("not_found", 404)
    if not hmac.compare_digest(photo.uploader_hash, device_hash(token)):
        return None, err("forbidden", 403)
    return photo, None


def _media_limit_mb(event, media_type):
    if media_type == Photo.MediaType.VIDEO:
        return min(event.max_video_size_mb, settings.MAX_VIDEO_UPLOAD_MB)
    return min(event.max_upload_size_mb, settings.MAX_IMAGE_UPLOAD_MB)


def _limit_bytes(event, media_type):
    return _media_limit_mb(event, media_type) * 1024 * 1024


@guest_api()
def consent(request, code):
    event, token, bad = _context(request, code, uploading=False)
    if bad:
        return bad
    UploadConsent.objects.get_or_create(
        event=event, device_hash=device_hash(token), defaults={"ip_hash": ip_hash(request)})
    return Response({"ok": True})


@guest_api()
def check_hash(request, code):
    event, token, bad = _context(request, code)
    if bad:
        return bad
    if (bad := _throttled(request, token, "hash", factor=5)):
        return bad
    h = str(request.data.get("hash", ""))
    if not HASH_RE.match(h):
        return err("invalid_hash", 400)
    return Response({"exists": Photo.objects.filter(event=event, content_hash=h, status__in=VISIBLE).exists()})


def _presign(event, photo, content_type):
    return get_storage().presign_upload(photo.upload_key, content_type, _limit_bytes(event, photo.media_type))


@guest_api()
def init_upload(request, code):
    event, token, bad = _context(request, code)
    if bad:
        return bad
    if (bad := _throttled(request, token, "up")):
        return bad
    dh = device_hash(token)
    if not UploadConsent.objects.filter(event=event, device_hash=dh).exists():
        return err("consent_required", 403)
    data = request.data
    media_type = str(data.get("media_type", "image")).lower()
    if media_type not in (Photo.MediaType.IMAGE, Photo.MediaType.VIDEO):
        return err("unsupported_type", 415)
    ctype = str(data.get("content_type", "")).lower()
    allowed = VIDEO_TYPES if media_type == Photo.MediaType.VIDEO else IMAGE_TYPES
    if ctype not in allowed:
        return err("unsupported_type", 415)
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        return err("invalid_size", 400)
    if size <= 0 or size > _limit_bytes(event, media_type):
        return err("too_large", 413, limit_mb=_media_limit_mb(event, media_type))
    h = str(data.get("hash", "") or "")
    if h and not HASH_RE.match(h):
        return err("invalid_hash", 400)
    raw_batch = data.get("batch_id")
    try:
        batch = uuid.UUID(str(raw_batch)) if raw_batch else uuid.uuid4()
    except (ValueError, TypeError, AttributeError):
        batch = uuid.uuid4()
    if Photo.objects.filter(event=event, batch_id=batch).count() >= event.max_photos_per_upload:
        return err("too_many", 400, limit=event.max_photos_per_upload)

    if h:
        existing = Photo.objects.filter(event=event, content_hash=h).first()
        if existing:
            if existing.status == Photo.Status.UPLOADING and existing.uploader_hash == dh:
                return Response({"photo_id": str(existing.id), "upload": _presign(event, existing, ctype)})
            return Response({"duplicate": True})
    try:
        photo = Photo.objects.create(
            event=event, uploader_hash=dh, ip_hash=ip_hash(request), content_hash=h, batch_id=batch,
            uploader_name=str(data.get("name", ""))[:60].strip(), declared_content_type=ctype,
            media_type=media_type)
    except IntegrityError:
        return Response({"duplicate": True})

    storage = get_storage()
    if media_type == Photo.MediaType.VIDEO:
        # Begin an S3 multipart upload and hand back the id; the client asks for a fresh
        # presigned URL per part just before uploading it, so 10-minute URL expiry is fine.
        multipart = storage.create_multipart(photo.upload_key, ctype)
        if multipart:
            photo.upload_id = multipart["upload_id"]
            photo.save(update_fields=["upload_id"])
            return Response({"photo_id": str(photo.id), "media_type": media_type,
                             "multipart": {"upload_id": multipart["upload_id"],
                                           "part_mb": settings.VIDEO_PART_MB}})
        return Response({"photo_id": str(photo.id), "media_type": media_type})
    return Response({"photo_id": str(photo.id), "media_type": media_type,
                     "upload": _presign(event, photo, ctype)})


@guest_api()
def upload_part(request, code, photo_id):
    """Fresh presigned PUT for one multipart part of a video (S3 backend only)."""
    event, token, bad = _context(request, code)
    if bad:
        return bad
    if (bad := _throttled(request, token, "up")):
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    if not photo.is_video:
        return err("not_supported", 400)
    if photo.status != Photo.Status.UPLOADING:
        return err("already_finalised", 409)
    upload_id = str(request.data.get("upload_id", "") or "")
    if not upload_id or upload_id != photo.upload_id:
        return err("upload_not_found", 400)
    try:
        part = int(request.data.get("part"))
    except (TypeError, ValueError):
        return err("invalid_part", 400)
    if not 1 <= part <= 10000:
        return err("invalid_part", 400)
    url = get_storage().presign_part(photo.upload_key, upload_id, part)
    if not url:
        return err("multipart_unavailable", 501)
    return Response({"url": url})


@guest_api(parsers=(MultiPartParser,))
def upload_file(request, code, photo_id):
    """Server-side fallback when direct-to-storage upload is unavailable (dev backend or outage)."""
    event, token, bad = _context(request, code)
    if bad:
        return bad
    if (bad := _throttled(request, token, "up")):
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    if photo.status != Photo.Status.UPLOADING:
        return err("already_finalised", 409)
    f = request.FILES.get("file")
    if f is None:
        return err("file_required", 400)
    if f.size > _limit_bytes(event, photo.media_type):
        return err("too_large", 413, limit_mb=_media_limit_mb(event, photo.media_type))
    get_storage().put(photo.upload_key, f, photo.declared_content_type)
    return Response({"ok": True})


@guest_api(parsers=(MultiPartParser,))
def upload_poster(request, code, photo_id):
    """Attach a small poster (captured client-side) to a video; stored as WebP."""
    event, token, bad = _context(request, code)
    if bad:
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    if not photo.is_video:
        return err("not_supported", 400)
    f = request.FILES.get("file")
    if f is None:
        return err("file_required", 400)
    if f.size > settings.POSTER_MAX_KB * 1024:
        return err("too_large", 413, limit_kb=settings.POSTER_MAX_KB)
    raw = f.read()
    fd, path = tempfile.mkstemp(prefix="vanpere-poster-", suffix=".img")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
        webp, _ = encode_webp(open_validated_path(path), 640, 80)
    except PhotoRejected as exc:
        return err("invalid_image", 422, detail=str(exc))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    get_storage().put(photo.key("poster"), webp, "image/webp")
    photo.poster_bytes = len(raw)
    photo.save(update_fields=["poster_bytes"])
    return Response({"ok": True, "bytes": len(webp)})


@guest_api()
def abort_upload(request, code, photo_id):
    """Cancel an in-progress upload (multipart or plain) and drop the row."""
    event, token, bad = _context(request, code)
    if bad:
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    if photo.status != Photo.Status.UPLOADING:
        return err("already_finalised", 409)
    discard_photo(photo)
    return Response({"ok": True})


@guest_api()
def finalise(request, code, photo_id):
    event, token, bad = _context(request, code)
    if bad:
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    if photo.status != Photo.Status.UPLOADING:
        return Response({"status": photo.status, "photo_id": str(photo.id)})
    storage = get_storage()
    if photo.is_video and photo.upload_id:
        raw = request.data.get("parts")
        if isinstance(raw, list) and raw:
            try:
                parts = [{"PartNumber": int(p["n"]), "ETag": str(p["e"])} for p in raw[:10000]]
            except (KeyError, TypeError, ValueError):
                return err("invalid_parts", 400)
            storage.complete_multipart(photo.upload_key, photo.upload_id, parts)
        # A fallback upload (parts absent) is completed by the server-side PUT already.
    if not storage.exists(photo.upload_key):
        return err("upload_missing", 400)
    try:
        photo = process_photo(photo.id)
    except PhotoRejected as exc:
        discard_photo(photo)
        return err("invalid_image", 422, detail=str(exc))
    except DuplicatePhoto:
        discard_photo(photo)
        return Response({"duplicate": True, "photo_id": str(photo.id)})
    return Response({"status": photo.status, "photo_id": str(photo.id),
                     "width": photo.width, "height": photo.height})