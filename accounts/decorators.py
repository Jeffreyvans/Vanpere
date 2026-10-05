from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def verified_required(view):
    """Login required, and the organiser's email must be verified (used from Stage 3)."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.email_verified:
            messages.warning(request, "Please verify your email first.")
            return redirect("accounts:home")
        return view(request, *args, **kwargs)
    return wrapper
