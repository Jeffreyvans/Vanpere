import uuid

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from accounts.decorators import staff_required

from events.models import Event
from photos.models import Photo, Report
from storage import get_storage

from . import services

S = Photo.Status
TABS = {"pending": S.PENDING, "approved": S.APPROVED, "rejected": S.REJECTED}
TOGGLES = {"allow_uploads", "allow_downloads", "moderation_enabled"}
PAGE_SIZE = 48


def _event(request, pk):
    """Owner-scoped lookup: other organisers' events are indistinguishable from missing ones."""
    return get_object_or_404(Event, pk=pk, owner=request.user)


def _redirect_back(request, fallback):
    nxt = request.POST.get("next", "")
    if nxt.startswith("/dashboard/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts=None):
        return redirect(nxt)
    return redirect(fallback)


def _stats(event):
    counts = {r["status"]: r["n"] for r in
              Photo.objects.filter(event=event).values("status").annotate(n=Count("id"))}
    return {
        "photos": sum(n for st, n in counts.items() if st != S.UPLOADING),
        "approved": counts.get(S.APPROVED, 0), "pending": counts.get(S.PENDING, 0),
        "rejected": counts.get(S.REJECTED, 0),
        "contributors": Photo.objects.filter(event=event).exclude(status=S.UPLOADING)
        .values("uploader_hash").distinct().count(),
        "open_reports": Photo.objects.filter(event=event, reports__dismissed=False).distinct().count(),
    }


@staff_required
def overview(request):
    events = list(Event.objects.filter(owner=request.user).annotate(
        n_photos=Count("photos", filter=~Q(photos__status=S.UPLOADING), distinct=True),
        n_pending=Count("photos", filter=Q(photos__status=S.PENDING), distinct=True),
        n_contributors=Count("photos__uploader_hash", filter=~Q(photos__status=S.UPLOADING), distinct=True),
    ).order_by("-created_at"))
    reports = {r["photo__event"]: r["n"] for r in
               Report.objects.filter(photo__event__owner=request.user, dismissed=False)
               .values("photo__event").annotate(n=Count("photo", distinct=True))}
    for e in events:
        e.n_reports = reports.get(e.pk, 0)
    used = sum(e.storage_used_bytes for e in events)
    quota = settings.ORGANISER_QUOTA_MB * 1024 * 1024
    return render(request, "dashboard/overview.html", {
        "events": events, "total_photos": sum(e.n_photos for e in events),
        "total_pending": sum(e.n_pending for e in events), "total_reports": sum(reports.values()),
        "used": used, "quota": quota, "over_quota": bool(quota) and used > quota,
        "near_quota": bool(quota) and quota * 0.8 < used <= quota,
        "quota_percent": min(100, round(used * 100 / quota)) if quota else 0})


@staff_required
def event_dashboard(request, pk):
    event = _event(request, pk)
    stats = _stats(event)
    return render(request, "dashboard/event.html", {
        "event": event, "stats": stats, "zip_large": stats["approved"] > settings.ZIP_WARN_PHOTOS})


@staff_required
def photos(request, pk):
    event = _event(request, pk)
    tab = request.GET.get("tab") or ("pending" if event.moderation_enabled else "approved")
    if tab not in TABS:
        tab = "approved"
    qs = Photo.objects.filter(event=event, status=TABS[tab])
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(uploader_name__icontains=q)
    sort = "old" if request.GET.get("sort") == "old" else "new"
    qs = qs.order_by("created_at" if sort == "old" else "-created_at", "id")
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    storage = get_storage()
    for p in page:
        p.thumb_url = storage.url(p.key("thumb"))
    counts = {r["status"]: r["n"] for r in
              Photo.objects.filter(event=event).values("status").annotate(n=Count("id"))}
    return render(request, "dashboard/photos.html", {
        "event": event, "tab": tab, "page": page, "q": q, "sort": sort,
        "counts": {t: counts.get(s, 0) for t, s in TABS.items()},
        "keep": urlencode({"tab": tab, "q": q, "sort": sort}), "here": request.get_full_path()})


@staff_required
def review(request, pk):
    """Quick-review mode: oldest pending photo first; keys A approve, R reject, S skip."""
    event = _event(request, pk)
    pending = Photo.objects.filter(event=event, status=S.PENDING).order_by("created_at", "id")
    total = pending.count()
    try:
        index = max(0, int(request.GET.get("i", 0)))
    except ValueError:
        index = 0
    photo = pending[index % total] if total else None
    if photo:
        photo.medium_url = get_storage().url(photo.key("medium"))
    return render(request, "dashboard/review.html", {
        "event": event, "photo": photo, "total": total, "next_i": (index + 1) % total if total else 0,
        "here": request.get_full_path()})


@staff_required
@require_POST
def bulk(request, pk):
    event = _event(request, pk)
    ids = []
    for raw in request.POST.getlist("ids"):
        try:
            ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    selected = Photo.objects.filter(event=event, pk__in=ids).exclude(status=S.UPLOADING)
    action = request.POST.get("action", "")
    count = selected.count()
    if not count:
        messages.warning(request, "Select at least one photo first.")
    elif action in ("approve", "restore"):
        services.set_status(selected, S.APPROVED)
        messages.success(request, f"{count} photo(s) approved.")
    elif action == "reject":
        services.set_status(selected, S.REJECTED, request.POST.get("reason", "")[:200].strip())
        messages.success(request, f"{count} photo(s) rejected.")
    elif action == "delete":
        services.delete_photos(event, selected)
        messages.success(request, f"{count} photo(s) permanently deleted.")
    elif action == "cover":
        photo = selected.filter(status=S.APPROVED).first()
        if count != 1 or photo is None:
            messages.error(request, "Choose exactly one approved photo for the cover.")
        else:
            services.set_cover(event, photo)
            messages.success(request, "Cover photo updated.")
    else:
        messages.error(request, "Unknown action.")
    return _redirect_back(request, reverse("dashboard:photos", args=[event.pk]))


@staff_required
def reports(request, pk):
    event = _event(request, pk)
    flagged = (Photo.objects.filter(event=event, reports__dismissed=False)
               .annotate(n_reports=Count("reports")).order_by("-n_reports", "-created_at")
               .prefetch_related(Prefetch("reports", queryset=Report.objects.filter(dismissed=False)
                                          .order_by("-created_at"), to_attr="open_reports")))
    storage = get_storage()
    rows = list(flagged)
    for p in rows:
        p.thumb_url = storage.url(p.key("thumb"))
    return render(request, "dashboard/reports.html", {"event": event, "photos": rows})


@staff_required
@require_POST
def report_action(request, pk, photo_id):
    event = _event(request, pk)
    photo = get_object_or_404(Photo, pk=photo_id, event=event)
    action = request.POST.get("action")
    if action == "dismiss":
        if photo.auto_hidden and photo.status == S.PENDING:
            Photo.objects.filter(pk=photo.pk).update(status=S.APPROVED, auto_hidden=False)
        photo.reports.filter(dismissed=False).update(dismissed=True)
        messages.success(request, "Reports dismissed.")
    elif action == "hide":
        services.set_status(Photo.objects.filter(pk=photo.pk), S.REJECTED, "Reported")
        photo.reports.filter(dismissed=False).update(dismissed=True)
        messages.success(request, "Photo hidden.")
    elif action == "delete":
        services.delete_photos(event, Photo.objects.filter(pk=photo.pk))
        messages.success(request, "Photo permanently deleted.")
    else:
        messages.error(request, "Unknown action.")
    return redirect("dashboard:reports", pk=event.pk)


@staff_required
def contributors(request, pk):
    event = _event(request, pk)
    rows = list(Photo.objects.filter(event=event).exclude(status=S.UPLOADING).values("uploader_hash")
                .annotate(n=Count("id"), approved=Count("id", filter=Q(status=S.APPROVED)),
                          last=Max("created_at")).order_by("-n"))
    names = {}
    for h, name in (Photo.objects.filter(event=event).exclude(uploader_name="")
                    .order_by("created_at").values_list("uploader_hash", "uploader_name")):
        names[h] = name
    for r in rows:
        r["name"] = names.get(r["uploader_hash"], "Anonymous")
        r["short"] = r["uploader_hash"][:6]
    return render(request, "dashboard/contributors.html", {"event": event, "rows": rows})


@staff_required
@require_POST
def contributor_remove(request, pk):
    event = _event(request, pk)
    device = request.POST.get("device", "")
    removed = services.delete_photos(event, Photo.objects.filter(event=event, uploader_hash=device)) if device else 0
    messages.success(request, f"Removed {removed} photo(s) from that contributor.")
    return redirect("dashboard:contributors", pk=event.pk)


@staff_required
def download_zip(request, pk):
    event = _event(request, pk)
    qs = Photo.objects.filter(event=event, status=S.APPROVED).order_by("created_at", "id")
    n = qs.count()
    if n == 0:
        messages.error(request, "There are no approved photos to download.")
        return redirect("dashboard:event", pk=event.pk)
    if n > settings.ZIP_MAX_PHOTOS:
        messages.error(request, f"This event has {n} photos; the ZIP limit is {settings.ZIP_MAX_PHOTOS}. "
                                "Download in parts by contributor or ask the administrator to raise ZIP_MAX_PHOTOS.")
        return redirect("dashboard:event", pk=event.pk)
    resp = StreamingHttpResponse(services.stream_zip(qs.iterator(), get_storage()), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="vanpere-{event.public_code}-photos.zip"'
    resp["Cache-Control"] = "no-store"
    return resp


@staff_required
@require_POST
def toggle(request, pk, field):
    event = _event(request, pk)
    if field not in TOGGLES:
        messages.error(request, "Unknown setting.")
    else:
        setattr(event, field, not getattr(event, field))
        event.save(update_fields=[field])
        messages.success(request, "Setting updated.")
    return redirect("dashboard:event", pk=event.pk)


@staff_required
def regenerate(request, pk):
    event = _event(request, pk)
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        event.regenerate_code()
        messages.success(request, "New link created. Print new QR codes: the old link no longer works.")
        return redirect("events:detail", pk=event.pk)
    return render(request, "dashboard/confirm.html", {
        "event": event, "title": "Regenerate the event code",
        "body": "Your current link and every printed or shared QR code will stop working. Guests will need the new link.",
        "button": "Regenerate code"})


@staff_required
def delete_event(request, pk):
    event = _event(request, pk)
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        services.purge_event_files(event)
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("dashboard:overview")
    return render(request, "dashboard/confirm.html", {
        "event": event, "title": "Delete this event",
        "body": "This permanently deletes the event, all photos and every stored file. It cannot be undone.",
        "button": "Delete event permanently", "danger": True})
