import hashlib
import hmac
import re

from django.conf import settings

from accounts.utils import client_ip

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def digest(value: str) -> str:
    """Keyed hash so tokens and IPs are never stored or logged in clear."""
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def device_token(request) -> str:
    token = request.headers.get("X-Device-Token") or request.COOKIES.get("vp_device") or ""
    return token if TOKEN_RE.match(token) else ""


def device_hash(token: str) -> str:
    return digest("dev:" + token)


def ip_hash(request) -> str:
    return digest("ip:" + client_ip(request))
