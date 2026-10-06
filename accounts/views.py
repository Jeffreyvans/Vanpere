from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .emails import VERIFY_SALT, send_verification_email
from .forms import ThrottledLoginForm
from .models import User


@login_required
def home(request):
    return render(request, "accounts/home.html")


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFY_MAX_AGE)
        user = User.objects.filter(pk=data["uid"], email=data["e"]).first()
    except (signing.BadSignature, signing.SignatureExpired, KeyError, TypeError, ValueError):
        user = None
    if user is None:
        return render(request, "accounts/message.html", {
            "title": "Link expired or invalid",
            "body": "This verification link is no longer valid. Sign in and request a new one."}, status=400)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    messages.success(request, "Your email is verified. You can now publish events.")
    return redirect("accounts:home" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
def resend_verification(request):
    if request.user.email_verified:
        messages.info(request, "Your email is already verified.")
    elif not cache.add(f"verify-resend:{request.user.pk}", 1, 60):
        messages.warning(request, "Please wait a minute before requesting another email.")
    else:
        send_verification_email(request.user)
        messages.success(request, "Verification email sent.")
    return redirect("accounts:home")


login_view = auth_views.LoginView.as_view(
    template_name="accounts/login.html", authentication_form=ThrottledLoginForm,
    redirect_authenticated_user=True)

password_reset = auth_views.PasswordResetView.as_view(
    template_name="accounts/password_reset_form.html",
    email_template_name="emails/password_reset.txt",
    html_email_template_name="emails/password_reset.html",
    subject_template_name="emails/password_reset_subject.txt",
    success_url=reverse_lazy("accounts:password_reset_done"),
    extra_email_context={"site_url": settings.SITE_URL})

password_reset_done = auth_views.PasswordResetDoneView.as_view(
    template_name="accounts/message.html",
    extra_context={"title": "Check your email",
                   "body": "If an account exists for that address, we have sent reset instructions."})

password_reset_confirm = auth_views.PasswordResetConfirmView.as_view(
    template_name="accounts/password_reset_confirm.html",
    success_url=reverse_lazy("accounts:password_reset_complete"))

password_reset_complete = auth_views.PasswordResetCompleteView.as_view(
    template_name="accounts/message.html",
    extra_context={"title": "Password updated", "body": "You can now sign in with your new password."})
