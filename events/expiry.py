"""Expiry lifecycle: mark expired, warn organisers, purge files after a grace period.

`run_expiry` is idempotent: every step records what it did on the event, so re-running changes
nothing. Logs counts and public codes only (never emails, IPs or tokens)."""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from storage import get_storage

from . import timeutils
from .emails import send_expiry_warning
from .models import Event

log = logging.getLogger("vanpere.expiry")


def purge_files(event, now):
    """Delete every stored file and photo/consent row, keeping only minimal event metadata."""
    get_storage().delete_prefix(f"events/{event.id}/")
    event.photos.all().delete()  # reports cascade
    event.consents.all().delete()
    Event.objects.filter(pk=event.pk).update(cover_image="", storage_used_bytes=0, files_purged_at=now)


def run_expiry(now=None, dry_run=False):
    now = now or timezone.now()
    summary = {"marked": 0, "warned": 0, "purged": 0, "email_failures": 0}

    for event in Event.objects.filter(expires_at__lt=now, expiry_marked_at__isnull=True):
        summary["marked"] += 1
        if not dry_run:
            Event.objects.filter(pk=event.pk).update(expiry_marked_at=now)

    thresholds = sorted(settings.EXPIRY_WARNING_DAYS)
    for event in Event.objects.filter(expires_at__gte=now, is_active=True).select_related("owner"):
        sent = set(event.warned_days)
        days = timeutils.days_remaining(event.expires_at, now)
        due = [d for d in thresholds if days <= d and d not in sent]
        if not due:
            continue
        summary["warned"] += 1
        if dry_run:
            continue
        try:
            send_expiry_warning(event, days)
        except Exception:  # not recorded, so the next run retries
            log.exception("expiry warning failed for event %s", event.public_code)
            summary["warned"] -= 1
            summary["email_failures"] += 1
            continue
        merged = ",".join(str(d) for d in sorted(sent | set(due), reverse=True))
        Event.objects.filter(pk=event.pk).update(warned_thresholds=merged)

    cutoff = now - timedelta(days=settings.PURGE_GRACE_DAYS)
    for event in Event.objects.filter(expires_at__lt=cutoff, files_purged_at__isnull=True):
        summary["purged"] += 1
        if not dry_run:
            purge_files(event, now)

    log.info("expire_events%s: %s", " (dry run)" if dry_run else "", summary)
    return summary
