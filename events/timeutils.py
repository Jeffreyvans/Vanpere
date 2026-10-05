"""Single source of truth for expiry maths. Stored in UTC, shown in Africa/Harare."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def get_tz():
    return ZoneInfo(settings.TIME_ZONE)


def local_date(dt):
    return dt.astimezone(get_tz()).date()


def local_today():
    return local_date(timezone.now())


def end_of_day(d: date) -> datetime:
    """Aware datetime for the last instant of `d` in the configured time zone."""
    return datetime.combine(d, time.max, tzinfo=get_tz())


def default_expires_at(event_date: date, days: int | None = None) -> datetime:
    days = settings.DEFAULT_EVENT_EXPIRY_DAYS if days is None else days
    return end_of_day(event_date + timedelta(days=days))


def is_expired(expires_at, now=None) -> bool:
    return (now or timezone.now()) > expires_at


def days_remaining(expires_at, now=None) -> int:
    """Whole local calendar days left; 0 on the expiry day itself or once expired."""
    now = now or timezone.now()
    return max(0, (local_date(expires_at) - local_date(now)).days)
