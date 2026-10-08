"""Content-Security-Policy (Django 5 has no built-in CSP). Skipped for the Django admin."""
from urllib.parse import urlparse

from django.conf import settings


def storage_origins():
    """Bucket origins the browser must reach (image URLs and direct uploads)."""
    if settings.STORAGE_BACKEND != "s3" or not settings.S3_BUCKET:
        return []
    bucket = settings.S3_BUCKET
    if settings.S3_ENDPOINT_URL:
        u = urlparse(settings.S3_ENDPOINT_URL)
        return [f"{u.scheme}://{u.netloc}", f"{u.scheme}://{bucket}.{u.netloc}"]
    region = settings.S3_REGION or "us-east-1"
    return [f"https://{bucket}.s3.{region}.amazonaws.com", f"https://s3.{region}.amazonaws.com"]


class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/admin/") or "Content-Security-Policy" in response:
            return response
        if settings.DEBUG and response.status_code >= 500:
            return response  # Django's debug page needs inline styles
        bucket = " ".join(storage_origins())
        response["Content-Security-Policy"] = "; ".join([
            "default-src 'self'", "script-src 'self'", "style-src 'self'",
            f"img-src 'self' data: blob: {bucket}".strip(),
            f"media-src 'self' blob: {bucket}".strip(),
            f"connect-src 'self' {bucket}".strip(),
            "font-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'",
            "frame-ancestors 'none'"])
        return response
