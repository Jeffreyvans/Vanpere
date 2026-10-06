from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm

from . import throttle
from .utils import client_ip


class ThrottledLoginForm(AuthenticationForm):
    """Email login with lockout per IP and per email."""
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))

    def clean(self):
        email = (self.cleaned_data.get("username") or "").lower()
        ip = client_ip(self.request)
        if email and throttle.is_locked(ip, email):
            raise forms.ValidationError(
                f"Too many failed attempts. Please try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes.",
                code="locked",
            )
        self.cleaned_data["username"] = email
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            if email:
                throttle.record_failure(ip, email)
            raise
        throttle.reset_email(ip, email)
        return cleaned
