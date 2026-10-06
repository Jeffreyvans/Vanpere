from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def staff_required(view):
    """Only the built-in administrator (staff/superuser) may manage events."""
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.warning(request, "Administrator access is required.")
            return redirect("accounts:home")
        return view(request, *args, **kwargs)
    return wrapper
