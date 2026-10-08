"""Guest gallery API: list, slideshow feed, download, report, delete. Every endpoint enforces
expiry, PIN and approval rules; the organiser bypasses expiry and PIN."""
import calendar
import hmac
import uuid
from datetime import datetime, timedelta, timezone as dt_tz

from django.conf import settings
from django.contrib.auth import get_user as user_from_session
from django.db.models import Count, F, Q
from django.db.models.functions import Greatest
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET
from rest_framework.response import Response

from events import pin
from events.models import Event
from storage import get_storage

from . import ratelimit
from .api import _own_photo, err, guest_api
from .models import Comment, Like, Photo, Report
from .security import device_hash, device_token, digest
from .services.image_pipeline import discard_photo
from accounts.utils import client_ip

APPROVED = Photo.Status.APPROVED


def _acting_user(request):
    """Session user, even when DRF empty authenticators overwrite request.user."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    dj = getattr(request, "_request", request)
    dj_user = getattr(dj, "user", None)
    if dj_user is not None and getattr(dj_user, "is_authenticated", False):
        return dj_user
    return user_from_session(dj)


def _check(request, code):
    """Return (event, is_owner, error) where error is (code, http_status) or None."""
    event = Event.objects.filter(public_code=code.upper(), is_active=True).first()
    if event is None:
        return None, False, ("not_found", 404)
    user = _acting_user(request)
    owner = bool(user and user.is_authenticated and event.owner_id == user.id)
    if not owner:
        if event.is_expired:
            return None, False, ("event_ended", 410)
        if not pin.is_unlocked(getattr(request, "_request", request), event):
            return None, False, ("pin_required", 403)
    return event, owner, None


def _cursor(photo):
    secs = calendar.timegm(photo.created_at.utctimetuple())
    return f"{secs}.{photo.created_at.microsecond:06d}_{photo.id}"


def _parse_cursor(raw):
    try:
        stamp, pid = raw.split("_", 1)
        secs, micro = stamp.split(".")
        return (datetime.fromtimestamp(int(secs), dt_tz.utc) + timedelta(microseconds=int(micro)),
                uuid.UUID(pid))
    except (AttributeError, ValueError):
        return None


def _item(photo, storage, mine, liked=False, likes=0, comments=0):
    base = {"id": str(photo.id), "w": photo.width, "h": photo.height, "mine": mine,
            "name": photo.uploader_name, "at": photo.created_at.isoformat(),
            "likes": likes, "liked": liked, "comments": comments}
    if photo.is_video:
        return {**base, "type": "video",
                "thumb": storage.url(photo.key("poster")) if photo.poster_bytes else None,
                "video": storage.url(photo.key("original"))}
    return {**base, "type": "image",
            "thumb": storage.url(photo.key("thumb")), "medium": storage.url(photo.key("medium"))}


def _no_store(resp):
    resp["Cache-Control"] = "no-store"
    return resp


@guest_api(methods=("GET",))
def photo_list(request, code):
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    try:
        limit = max(1, min(60, int(request.query_params.get("limit", 24))))
    except ValueError:
        limit = 24
    base = Photo.objects.filter(event=event, status=APPROVED)
    qs = base.order_by("-created_at", "-id")
    cur = _parse_cursor(request.query_params.get("cursor"))
    if cur:
        qs = qs.filter(Q(created_at__lt=cur[0]) | Q(created_at=cur[0], id__lt=cur[1]))
    rows = list(qs[: limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    token = device_token(request)
    dh = device_hash(token) if token else None
    storage = get_storage()
    ids = [p.id for p in rows]
    liked_ids = set(Like.objects.filter(photo_id__in=ids, actor_hash=dh).values_list("photo_id", flat=True)) \
        if dh else set()
    like_counts = {r["photo_id"]: r["n"] for r in
                   Like.objects.filter(photo_id__in=ids).values("photo_id").annotate(n=Count("id"))}
    comment_counts = {r["photo_id"]: r["n"] for r in
                      Comment.objects.filter(photo_id__in=ids).values("photo_id").annotate(n=Count("id"))}
    items = [_item(p, storage, bool(dh) and hmac.compare_digest(p.uploader_hash, dh),
                   liked=p.id in liked_ids, likes=like_counts.get(p.id, 0),
                   comments=comment_counts.get(p.id, 0)) for p in rows]
    return _no_store(Response({"photos": items, "next": _cursor(rows[-1]) if more else None,
                               "count": base.count()}))


@guest_api(methods=("GET",))
def slideshow_data(request, code):
    """Latest approved photos with fresh URLs; polled by the venue slideshow."""
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    storage = get_storage()
    rows = Photo.objects.filter(event=event, status=APPROVED).order_by("-created_at", "-id")[:300]
    return _no_store(Response({"name": event.name, "photos": [
        {"id": str(p.id), "type": "video" if p.is_video else "image",
         "medium": storage.url(p.key("poster") if p.is_video and p.poster_bytes else p.key("medium"))}
        for p in rows]}))


@require_GET
def download(request, code, photo_id):
    """Redirect to a short-lived download URL: original if allowed (or organiser), else medium."""
    event, owner, bad = _check(request, code)
    if bad:
        return JsonResponse({"error": bad[0]}, status=bad[1])
    qs = Photo.objects.filter(pk=photo_id, event=event)
    if not owner:
        qs = qs.filter(status=APPROVED)
    photo = qs.first()
    if photo is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if photo.is_video:
        # Videos have no preview derivative, so a download always serves the original.
        version = "original"
        ext = photo.original_extension or "mp4"
    else:
        version = "original" if (event.allow_downloads or owner) else "medium"
        ext = photo.original_extension or "jpg"
    name = f"vanpere-{event.public_code}-{str(photo.id)[:8]}.{ext}"
    return HttpResponseRedirect(get_storage().url(photo.key(version), expires=300, download_name=name))


def _token(request):
    token = device_token(request)
    return token, (None if token else err("device_token_required", 400))


@guest_api()
def photo_report(request, code, photo_id):
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    token, bad = _token(request)
    if bad:
        return bad
    if not (ratelimit.hit("rep:dev", digest(token), settings.REPORT_RATE_PER_DEVICE)
            and ratelimit.hit("rep:ip", digest(client_ip(request)), settings.REPORT_RATE_PER_IP)):
        return err("rate_limited", 429)
    reason = str(request.data.get("reason", ""))
    if reason not in Report.Reason.values:
        return err("invalid_reason", 400)
    photo = Photo.objects.filter(pk=photo_id, event=event, status=APPROVED).first()
    if photo is None:
        return err("not_found", 404)
    Report.objects.get_or_create(
        photo=photo, reporter_hash=device_hash(token),
        defaults={"reason": reason, "note": str(request.data.get("note", ""))[:300].strip()})
    hidden = False
    if Report.objects.filter(photo=photo, dismissed=False).count() >= settings.REPORT_AUTO_HIDE_THRESHOLD:
        Photo.objects.filter(pk=photo.pk, status=APPROVED).update(status=Photo.Status.PENDING, auto_hidden=True)
        hidden = True
    return Response({"ok": True, "hidden": hidden})


@guest_api()
def photo_delete(request, code, photo_id):
    """A guest deletes their own upload from the same device."""
    event = Event.objects.filter(public_code=code.upper(), is_active=True).first()
    if event is None:
        return err("not_found", 404)
    token, bad = _token(request)
    if bad:
        return bad
    photo, bad = _own_photo(event, token, photo_id)
    if bad:
        return bad
    freed = photo.total_bytes
    discard_photo(photo)
    Event.objects.filter(pk=event.pk).update(storage_used_bytes=Greatest(F("storage_used_bytes") - freed, 0))
    return Response({"ok": True})
