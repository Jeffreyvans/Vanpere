"""Login throttling per IP and per email, backed by Django's cache (DB cache)."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _h(value):
    return hashlib.sha256(f"{settings.SECRET_KEY}:{value}".encode()).hexdigest()[:32]


def _keys(ip, email):
    return f"login-fail:ip:{_h(ip)}", f"login-fail:email:{_h(email.lower())}"


def _timeout():
    return settings.LOGIN_LOCKOUT_MINUTES * 60


def is_locked(ip, email):
    return any((cache.get(k) or 0) >= settings.LOGIN_MAX_FAILURES for k in _keys(ip, email))


def record_failure(ip, email):
    for key in _keys(ip, email):
        cache.add(key, 0, _timeout())
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, _timeout())


def reset_email(ip, email):
    """Clear the email counter after a successful login (the IP counter keeps running)."""
    cache.delete(_keys(ip, email)[1])
