def client_ip(request):
    """Best-effort client IP (first X-Forwarded-For entry behind Render's proxy)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
