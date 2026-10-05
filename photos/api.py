"""Guest upload API: consent, duplicate check, presigned init, server fallback, finalise."""
import hmac
import re
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
from accounts.utils import client_ip

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
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


def _limit_bytes(event):
    return event.max_upload_size_mb * 1024 * 1024


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
    return get_storage().presign_upload(photo.upload_key, content_type, _limit_bytes(event))


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
    ctype = str(data.get("content_type", "")).lower()
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        return err("invalid_size", 400)
    if ctype not in ALLOWED_TYPES:
        return err("unsupported_type", 415)
    if size <= 0 or size > _limit_bytes(event):
        return err("too_large", 413, limit_mb=event.max_upload_size_mb)
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
            uploader_name=str(data.get("name", ""))[:60].strip(), declared_content_type=ctype)
    except IntegrityError:
        return Response({"duplicate": True})
    return Response({"photo_id": str(photo.id), "upload": _presign(event, photo, ctype)})


@guest_api(parsers=(MultiPartParser,))
def upload_file(request, code, photo_id):
    """Server-side fallback when direct-to-storage upload is unavailable."""
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
    if f.size > _limit_bytes(event):
        return err("too_large", 413, limit_mb=event.max_upload_size_mb)
    get_storage().put(photo.upload_key, f, photo.declared_content_type)
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
    if not get_storage().exists(photo.upload_key):
        return err("upload_missing", 400)
    try:
        photo = process_photo(photo.id)
    except PhotoRejected as exc:
        discard_photo(photo)
        return err("invalid_image", 422, detail=str(exc))
    except DuplicatePhoto:
        discard_photo(photo)
        return Response({"duplicate": True})
    return Response({"status": photo.status, "photo_id": str(photo.id),
                     "width": photo.width, "height": photo.height})
