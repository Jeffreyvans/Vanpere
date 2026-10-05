from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from . import throttle
from .models import User
from .utils import client_ip


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = User
        fields = ("full_name", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            try:
                validate_password(p1, User(email=data.get("email", ""), full_name=data.get("full_name", "")))
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


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
