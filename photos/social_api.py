"""Guest social API: comments and likes.

Every endpoint enforces the same rules as the gallery: approved photos only, and expiry,
PIN and active-state checks for guests via ``gallery_api._check``. The organiser bypasses.
Comment bodies are plain text: the server strips control characters, enforces a length cap
and all render paths escape (Django templates and client-side ``textContent``), so HTML or
script never reaches the page. Like counts are always server-authoritative.
"""
import hmac
import unicodedata

from django.conf import settings
from django.db.models import Count
from rest_framework.response import Response

from accounts.utils import client_ip

from . import ratelimit
from .api import err, guest_api
from .gallery_api import _check, _no_store, _token
from .models import Comment, Like, Photo
from .security import device_hash, digest

APPROVED = Photo.Status.APPROVED


def _is_control(ch):
    return unicodedata.category(ch).startswith("C") and ch not in "\n\t"


def _clean_comment(raw):
    """Drop Unicode control characters (kept: tab/newline) and trim. Visible text is untouched."""
    text = str(raw or "").replace("\r\n", "\n")
    text = "".join(ch for ch in text if not _is_control(ch))
    return text.strip()


def _clean_name(raw):
    return "".join(ch for ch in str(raw or "") if not _is_control(ch)).strip()[:40]


def _comment_json(comment, actor_hash):
    return {"id": str(comment.id), "name": comment.name, "body": comment.body,
            "at": comment.created_at.isoformat(),
            "mine": bool(actor_hash) and hmac.compare_digest(comment.actor_hash, actor_hash)}


def _approved_photo(event, photo_id):
    return Photo.objects.filter(pk=photo_id, event=event, status=APPROVED).first()


@guest_api(methods=("GET",))
def comment_list(request, code, photo_id):
    """Newest-up-to-limit comments for one photo, returned oldest-first for reading."""
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    photo = _approved_photo(event, photo_id)
    if photo is None:
        return err("not_found", 404)
    try:
        limit = max(1, min(100, int(request.query_params.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    token, _ = _token(request)
    dh = device_hash(token) if token else None
    rows = list(Comment.objects.filter(photo=photo).order_by("-created_at", "-id")[:limit])
    return _no_store(Response({
        "comments": [_comment_json(c, dh) for c in reversed(rows)],
        "count": Comment.objects.filter(photo=photo).count()}))


@guest_api()
def comment_create(request, code, photo_id):
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    token, bad = _token(request)
    if bad:
        return bad
    if not (ratelimit.hit("cm:dev", digest(token), settings.COMMENT_RATE_PER_DEVICE)
            and ratelimit.hit("cm:ip", digest(client_ip(request)), settings.COMMENT_RATE_PER_IP)):
        return err("rate_limited", 429)
    body = _clean_comment(request.data.get("body"))
    if not body:
        return err("body_required", 400)
    if len(body) > settings.COMMENT_MAX_LENGTH:
        return err("too_long", 400, max=settings.COMMENT_MAX_LENGTH)
    photo = _approved_photo(event, photo_id)
    if photo is None:
        return err("not_found", 404)
    dh = device_hash(token)
    comment = Comment.objects.create(
        photo=photo, actor_hash=dh, name=_clean_name(request.data.get("name")), body=body)
    return _no_store(Response({"ok": True, "comment": _comment_json(comment, dh),
                               "count": Comment.objects.filter(photo=photo).count()}))


@guest_api()
def comment_delete(request, code, photo_id, comment_id):
    """A guest deletes only their own comment (from the same device)."""
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    token, bad = _token(request)
    if bad:
        return bad
    comment = (Comment.objects.filter(pk=comment_id, photo_id=photo_id, photo__event=event)
               .select_related("photo").first())
    if comment is None:
        return err("not_found", 404)
    if not hmac.compare_digest(comment.actor_hash, device_hash(token)):
        return err("forbidden", 403)
    comment.delete()
    return _no_store(Response({"ok": True, "count": Comment.objects.filter(photo=comment.photo_id).count()}))


@guest_api()
def like_toggle(request, code, photo_id):
    """Flip the current device's like on an approved photo; count comes from the server."""
    event, _, bad = _check(request, code)
    if bad:
        return err(*bad)
    token, bad = _token(request)
    if bad:
        return bad
    if not (ratelimit.hit("lk:dev", digest(token), settings.LIKE_RATE_PER_DEVICE)
            and ratelimit.hit("lk:ip", digest(client_ip(request)), settings.LIKE_RATE_PER_IP)):
        return err("rate_limited", 429)
    photo = _approved_photo(event, photo_id)
    if photo is None:
        return err("not_found", 404)
    dh = device_hash(token)
    liked = Like.objects.filter(photo=photo, actor_hash=dh).exists()
    if liked:
        Like.objects.filter(photo=photo, actor_hash=dh).delete()
    else:
        Like.objects.create(photo=photo, actor_hash=dh)
    return _no_store(Response({"liked": not liked, "count": Like.objects.filter(photo=photo).count()}))


def _like_counts(photo_ids):
    qs = Like.objects.filter(photo_id__in=photo_ids).values("photo_id").annotate(n=Count("id"))
    return {r["photo_id"]: r["n"] for r in qs}


def _comment_counts(photo_ids):
    qs = Comment.objects.filter(photo_id__in=photo_ids).values("photo_id").annotate(n=Count("id"))
    return {r["photo_id"]: r["n"] for r in qs}