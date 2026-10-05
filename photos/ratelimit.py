from django.core.cache import cache


def hit(scope: str, ident: str, limit: int, window: int = 3600) -> bool:
    """Count one request; return False once `limit` is exceeded within the window."""
    key = f"rl:{scope}:{ident}"
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count <= limit
