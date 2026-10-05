"""Viewing-PIN session memory and attempt throttling."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(event, ip):
    h = hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode()).hexdigest()[:24]
    return f"pin-fail:{event.pk}:{h}"


def is_locked(event, ip):
    return (cache.get(_key(event, ip)) or 0) >= settings.LOGIN_MAX_FAILURES


def record_failure(event, ip):
    key, timeout = _key(event, ip), settings.LOGIN_LOCKOUT_MINUTES * 60
    cache.add(key, 0, timeout)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout)


def session_key(event):
    return f"pin_ok:{event.public_code}"


def is_unlocked(request, event):
    return (not event.has_pin) or bool(request.session.get(session_key(event)))


def unlock(request, event):
    request.session[session_key(event)] = True
