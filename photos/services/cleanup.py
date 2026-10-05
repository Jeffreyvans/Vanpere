import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from photos.models import Photo

from .image_pipeline import discard_photo

log = logging.getLogger("vanpere.cleanup")


def cleanup_orphans(now=None, max_age_hours=None, dry_run=False):
    """Remove uploads that were never finalised (stored objects and database rows)."""
    hours = settings.ORPHAN_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
    cutoff = (now or timezone.now()) - timedelta(hours=hours)
    stale = list(Photo.objects.filter(status=Photo.Status.UPLOADING, created_at__lt=cutoff))
    if not dry_run:
        for photo in stale:
            discard_photo(photo)
    summary = {"removed": len(stale)}
    log.info("cleanup_orphans%s: %s", " (dry run)" if dry_run else "", summary)
    return summary
