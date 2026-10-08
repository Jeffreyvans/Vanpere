from django.shortcuts import get_object_or_404, render

from events.models import Event


def upload_page(request, code):
    event = get_object_or_404(Event, public_code=code.upper(), is_active=True)
    closed = "ended" if event.is_expired else ("disabled" if not event.allow_uploads else "")
    return render(request, "photos/upload.html", {"event": event, "closed": closed})


import base64
import io
import re
import time

from django.core import signing
from django.http import FileResponse, Http404, HttpResponse

from events import pin
from events.qr import qr_svg
from storage import get_storage

from .models import Photo

KEY_RE = re.compile(r"^events/([0-9a-f-]{36})/([0-9a-f-]{36})/(original|medium|thumb|poster)\.([a-z0-9]+)$")
EXT_CTYPE = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
             "webp": "image/webp", "heic": "image/heic", "heif": "image/heif",
             "gif": "image/gif", "mp4": "video/mp4", "mov": "video/quicktime",
             "webm": "video/webm", "m4v": "video/m4v", "3gp": "video/3gpp",
             "mkv": "video/x-matroska"}
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$", re.IGNORECASE)
_RANGE_CHUNK = 1024 * 1024  # local-backend only: bound how much we stage in memory for a range


def _is_owner(request, event):
    return request.user.is_authenticated and event.owner_id == request.user.id


def _page_state(request, event):
    owner = _is_owner(request, event)
    return (event.is_expired and not owner), (not owner and not pin.is_unlocked(request, event))


def gallery_page(request, code):
    event = get_object_or_404(Event, public_code=code.upper(), is_active=True)
    expired, needs_pin = _page_state(request, event)
    return render(request, "photos/gallery.html", {
        "event": event, "expired": expired, "needs_pin": needs_pin, "next": request.path})


def slideshow_page(request, code):
    event = get_object_or_404(Event, public_code=code.upper(), is_active=True)
    expired, needs_pin = _page_state(request, event)
    try:
        interval = max(3, min(30, int(request.GET.get("interval", 6))))
    except ValueError:
        interval = 6
    qr = base64.b64encode(qr_svg(event.public_url)).decode()
    return render(request, "photos/slideshow.html", {
        "event": event, "expired": expired, "needs_pin": needs_pin, "next": request.path,
        "interval": interval, "qr_uri": f"data:image/svg+xml;base64,{qr}",
        "short_url": event.public_url.split("://", 1)[-1]})


def _range_response(request, storage, key, content_type):
    """Byte-range response for local-backend video playback (dev only; prod uses S3 presigned)."""
    total = storage.size(key)
    m = _RANGE_RE.match(request.META.get("HTTP_RANGE", ""))
    start = end = None
    if m:
        s, e = m.groups()
        if s:
            start = int(s)
        if e:
            end = min(int(e), total - 1)
    if start is None:
        start = max(0, total - _RANGE_CHUNK)
        end = total - 1
    elif end is None:
        end = min(start + _RANGE_CHUNK - 1, total - 1)
    if start > end or start >= total:
        resp = HttpResponse(status=416)
        resp["Content-Range"] = f"bytes */{total}"
        return resp
    stream = storage.get_stream(key)
    try:
        stream.seek(start)
        data = stream.read(end - start + 1)
    finally:
        stream.close()
    resp = FileResponse(io.BytesIO(data), status=206, content_type=content_type)
    resp["Content-Range"] = f"bytes {start}-{end}/{total}"
    resp["Accept-Ranges"] = "bytes"
    resp["Content-Length"] = len(data)
    return resp


def media(request, token):
    """Serve local-backend photo files for a signed, expiring URL, re-checking access every time."""
    try:
        data = signing.loads(token, salt="media")
    except signing.BadSignature:
        raise Http404
    match = KEY_RE.match(data.get("k", ""))
    if not match or data.get("e", 0) < time.time():
        raise Http404
    photo = Photo.objects.select_related("event").filter(pk=match.group(2), event_id=match.group(1)).first()
    if photo is None:
        raise Http404
    event = photo.event
    if not _is_owner(request, event):
        if photo.status != Photo.Status.APPROVED or event.is_expired or not event.is_active:
            raise Http404
        if not pin.is_unlocked(request, event):
            raise Http404
    storage = get_storage()
    if not storage.exists(data["k"]):
        raise Http404
    content_type = EXT_CTYPE.get(match.group(4), "application/octet-stream")
    if content_type.startswith("video/") and "HTTP_RANGE" in request.META:
        resp = _range_response(request, storage, data["k"], content_type)
        resp["Cache-Control"] = "private, max-age=300"
        return resp
    resp = FileResponse(storage.get_stream(data["k"]), content_type=content_type)
    resp["Cache-Control"] = "private, max-age=300"
    resp["Accept-Ranges"] = "bytes"
    if data.get("d"):
        resp["Content-Disposition"] = f'attachment; filename="{data["d"]}"'
    return resp


import hashlib  # noqa: E402

from django.conf import settings  # noqa: E402
from django.shortcuts import redirect  # noqa: E402
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse  # noqa: E402

SW_ASSETS = ["css/main.css", "img/favicon.svg", "js/upload/uploader.js", "js/upload/api.js",
             "js/upload/device.js", "js/upload/hash.js", "js/upload/queue.js"]


def _photo_for_page(request, event, photo_id):
    photo = get_object_or_404(Photo, pk=photo_id, event=event)
    if photo.status != Photo.Status.APPROVED and not _is_owner(request, event):
        raise Http404
    return photo


def photo_page(request, code, photo_id):
    """Shareable page for one photo. Same rules as the gallery: approved only, expiry, PIN."""
    event = get_object_or_404(Event, public_code=code.upper(), is_active=True)
    photo = _photo_for_page(request, event, photo_id)
    expired, needs_pin = _page_state(request, event)
    site = settings.SITE_URL.rstrip("/")
    url = site + reverse("photos:photo", args=[event.public_code, photo.id])
    ctx = {"event": event, "photo": photo, "expired": expired, "needs_pin": needs_pin, "next": request.path,
           "share_url": url, "share_subject": f"A photo from {event.name}",
           "share_text": f"A photo from {event.name} on VanPere Digital: {url}",
           "is_video": photo.is_video}
    if not expired and not needs_pin:
        if photo.is_video:
            if photo.poster_bytes:
                ctx["poster_url"] = get_storage().url(photo.key("poster"))
        else:
            ctx["image_url"] = get_storage().url(photo.key("medium"))
        if not event.has_pin:  # crawlers have no session, so previews only work without a PIN
            og_key = None
            if photo.is_video and photo.poster_bytes:
                og_key = photo.key("poster")
            elif not photo.is_video:
                og_key = photo.key("medium")
            if og_key:
                ctx["og_image"] = site + reverse("photos:photo_og", args=[event.public_code, photo.id])
    return render(request, "photos/photo.html", ctx)


def photo_og(request, code, photo_id):
    """Stable, non-expiring image URL for link previews (only for approved photos of open, PIN-free events)."""
    event = get_object_or_404(Event, public_code=code.upper(), is_active=True)
    photo = get_object_or_404(Photo, pk=photo_id, event=event, status=Photo.Status.APPROVED)
    if event.has_pin or event.is_expired:
        raise Http404
    storage = get_storage()
    if photo.is_video and not photo.poster_bytes:
        raise Http404
    key = photo.key("poster") if photo.is_video else photo.key("medium")
    if settings.STORAGE_BACKEND == "s3":
        return redirect(storage.url(key, expires=300))
    if not storage.exists(key):
        raise Http404
    resp = FileResponse(storage.get_stream(key), content_type="image/webp")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


def service_worker(request):
    """Minimal service worker served from /event/ so its scope is limited to event pages."""
    urls = [static(p) for p in SW_ASSETS]
    version = hashlib.sha1("".join(urls).encode()).hexdigest()[:10]
    resp = render(request, "sw.js", {"urls": urls, "version": version}, content_type="text/javascript")
    resp["Service-Worker-Allowed"] = "/event/"
    resp["Cache-Control"] = "no-cache"
    return resp
