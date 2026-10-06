from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required
from accounts.utils import client_ip
from storage import get_storage

from . import pin, qr
from .emails import send_event_created
from .forms import EventForm
from .models import Event


def _owned(request, pk):
    return get_object_or_404(Event, pk=pk, owner=request.user)


def _share_context(event):
    url = event.public_url
    return {"share_url": url, "share_subject": f"Photos from {event.name}",
            "share_text": f"Share your photos from {event.name} on VanPere Digital: {url}"}


# ---- organiser views (owner-scoped) ----
@staff_required
def event_list(request):
    return render(request, "events/list.html", {"events": request.user.events.all()})


@staff_required
def event_create(request):
    form = EventForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(owner=request.user)
        send_event_created(event)
        messages.success(request, "Your event is live. Share the link or QR code with your guests.")
        return redirect("events:detail", pk=event.pk)
    return render(request, "events/form.html", {
        "form": form, "default_days": settings.DEFAULT_EVENT_EXPIRY_DAYS})


@staff_required
def event_edit(request, pk):
    event = _owned(request, pk)
    if event.files_purged_at:
        messages.error(request, "This event's files were deleted after it expired, so it cannot be reopened.")
        return redirect("events:detail", pk=event.pk)
    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Event updated.")
        return redirect("events:detail", pk=event.pk)
    return render(request, "events/form.html", {
        "form": form, "event": event, "default_days": settings.DEFAULT_EVENT_EXPIRY_DAYS})


@staff_required
def event_detail(request, pk):
    event = _owned(request, pk)
    return render(request, "events/detail.html", {"event": event, **_share_context(event)})


@staff_required
def qr_png(request, pk):
    event = _owned(request, pk)
    resp = HttpResponse(qr.qr_png(event.public_url), content_type="image/png")
    resp["Content-Disposition"] = f'inline; filename="vanpere-{event.public_code}-qr.png"'
    return resp


@staff_required
def qr_svg(request, pk):
    event = _owned(request, pk)
    resp = HttpResponse(qr.qr_svg(event.public_url), content_type="image/svg+xml")
    resp["Content-Disposition"] = f'inline; filename="vanpere-{event.public_code}-qr.svg"'
    return resp


@staff_required
def poster(request, pk, size):
    event = _owned(request, pk)
    if size not in qr.POSTER_SIZES:
        raise Http404
    resp = HttpResponse(qr.poster_pdf(event.name, event.public_url, size), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="vanpere-{event.public_code}-{size}.pdf"'
    return resp


# ---- public (guest) views ----
def _public(code):
    return get_object_or_404(Event, public_code=code.upper(), is_active=True)


def event_public(request, code):
    event = _public(code)
    if event.cover_image:
        og_image = settings.SITE_URL.rstrip("/") + reverse("events:cover", args=[event.public_code])
    else:
        og_image = settings.SITE_URL.rstrip("/") + static("img/og-default.png")
    return render(request, "events/public.html", {
        "event": event, "expired": event.is_expired, "og_image": og_image,
        "needs_pin": not pin.is_unlocked(request, event), **_share_context(event)})


def event_cover(request, code):
    event = _public(code)
    if not event.cover_image:
        raise Http404
    storage = get_storage()
    if settings.STORAGE_BACKEND == "s3":
        return redirect(storage.url(event.cover_image, expires=3600))
    if not storage.exists(event.cover_image):
        raise Http404
    resp = FileResponse(storage.get_stream(event.cover_image), content_type="image/jpeg")
    resp["Cache-Control"] = "public, max-age=3600"
    return resp


@require_POST
def event_pin(request, code):
    event = _public(code)
    ip = client_ip(request)
    if pin.is_locked(event, ip):
        messages.error(request, f"Too many attempts. Try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes.")
    elif event.check_pin(request.POST.get("pin", "")):
        pin.unlock(request, event)
    else:
        pin.record_failure(event, ip)
        messages.error(request, "That PIN is not correct.")
    nxt = request.POST.get("next", "")
    if nxt.startswith(f"/event/{event.public_code}/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=None):
        return redirect(nxt)
    return redirect("events:public", code=event.public_code)
