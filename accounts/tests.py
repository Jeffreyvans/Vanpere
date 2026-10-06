from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse

from .emails import send_verification_email
from .models import User

PW = "S0meLongPass!9"
ADMIN_EMAIL = "operator@example.com"


class RegistrationDisabledTests(TestCase):
    def test_register_url_is_gone(self):
        self.assertEqual(self.client.get("/accounts/register/").status_code, 404)
        self.assertEqual(self.client.post("/accounts/register/", {
            "full_name": "Ann", "email": "a@example.com", "password1": PW, "password2": PW,
        }).status_code, 404)
        self.assertFalse(User.objects.exists())

    def test_no_registration_endpoints_anywhere(self):
        for path in ("/accounts/register/", "/accounts/signup/", "/register/", "/signup/",
                     "/api/accounts/register/", "/api/register/"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
            self.assertEqual(self.client.post(path, {"email": "a@example.com"}).status_code, 404, path)
        with self.assertRaises(NoReverseMatch):
            reverse("accounts:register")
        self.assertFalse(Path("templates/accounts/register.html").exists(),
                         "the registration form template must be removed")
        self.assertFalse(User.objects.exists())

    def test_landing_and_login_have_no_registration_links(self):
        home = self.client.get("/").content.decode()
        login = self.client.get(reverse("accounts:login")).content.decode()
        self.assertNotIn("/accounts/register/", home)
        self.assertNotIn("/accounts/register/", login)
        self.assertNotIn("Create an account", login)


class AdminBootstrapTests(TestCase):
    def test_create_admin_hashes_password_and_is_idempotent(self):
        with override_settings(ADMIN_EMAIL=ADMIN_EMAIL, ADMIN_PASSWORD=PW):
            out = StringIO()
            call_command("create_admin", stdout=out)
            first = out.getvalue()
            user = User.objects.get(email=ADMIN_EMAIL)
            self.assertTrue(user.is_staff and user.is_superuser and user.email_verified)
            self.assertTrue(user.check_password(PW))
            self.assertNotEqual(user.password, PW)
            self.assertTrue(user.has_usable_password())
            self.assertNotIn(PW, first)
            user.set_password("OtherLongPass!9")
            user.save()
            out2 = StringIO()
            call_command("create_admin", stdout=out2)
            user.refresh_from_db()
            self.assertEqual(User.objects.filter(email=ADMIN_EMAIL).count(), 1)
            self.assertTrue(user.check_password("OtherLongPass!9"))
            self.assertFalse(user.check_password(PW))
            self.assertNotIn(PW, out2.getvalue())
            self.assertNotIn("OtherLongPass!9", out2.getvalue())

    def test_create_admin_requires_environment(self):
        with override_settings(ADMIN_EMAIL="", ADMIN_PASSWORD=""):
            with self.assertRaises(CommandError):
                call_command("create_admin", stdout=StringIO())

    def test_built_in_administrator_can_log_in(self):
        with override_settings(ADMIN_EMAIL=ADMIN_EMAIL, ADMIN_PASSWORD=PW):
            call_command("create_admin", stdout=StringIO())
        r = self.client.post(reverse("accounts:login"), {"username": ADMIN_EMAIL, "password": PW})
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)


class VerificationAndEmailTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            ADMIN_EMAIL, PW, email_verified=False, is_staff=True, is_superuser=True)

    def test_filebased_backend_does_not_raise_oserror(self):
        """Windows consoles raise OSError [Errno 22] on console.EmailBackend.flush."""
        with TemporaryDirectory() as tmp:
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend",
                EMAIL_FILE_PATH=tmp,
            ):
                send_verification_email(self.user)
                written = list(Path(tmp).iterdir())
                self.assertTrue(written)
                body = written[0].read_text(encoding="utf-8", errors="replace")
                self.assertIn("VanPere Digital", body)
                self.assertIn("verify", body.lower())

    def test_verify_link_marks_verified(self):
        send_verification_email(self.user)
        from django.conf import settings as s
        import re
        link = re.search(r"http\S+/accounts/verify/\S+/", mail.outbox[0].body).group(0)
        self.client.get(link[len(s.SITE_URL):])
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_bad_token_rejected(self):
        self.assertEqual(self.client.get(reverse("accounts:verify", args=["bad"])).status_code, 400)

    def test_resend_cooldown(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:resend_verification"))
        self.client.post(reverse("accounts:resend_verification"))
        self.assertEqual(len(mail.outbox), 1)


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(ADMIN_EMAIL, PW, is_staff=True, is_superuser=True, email_verified=True)

    def _login(self, email, pw):
        return self.client.post(reverse("accounts:login"), {"username": email, "password": pw})

    def test_email_lockout(self):
        for _ in range(settings.LOGIN_MAX_FAILURES):
            self._login(ADMIN_EMAIL, "wrong")
        r = self._login(ADMIN_EMAIL, PW)
        self.assertContains(r, "Too many failed attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ip_lockout_across_emails(self):
        for i in range(settings.LOGIN_MAX_FAILURES):
            self._login(f"x{i}@example.com", "wrong")
        self.assertContains(self._login(ADMIN_EMAIL, PW), "Too many failed attempts")

    def test_successful_login(self):
        self._login(ADMIN_EMAIL.upper().replace("O", "O"), PW)  # keep case-insensitive email
        self.client.post(reverse("accounts:login"), {"username": "Operator@example.com", "password": PW})
        self.assertIn("_auth_user_id", self.client.session)


class PasswordResetTests(TestCase):
    def test_reset_email_is_branded_html_and_text(self):
        User.objects.create_user(ADMIN_EMAIL, PW, is_staff=True, is_superuser=True, email_verified=True)
        self.client.post(reverse("accounts:password_reset"), {"email": ADMIN_EMAIL})
        msg = mail.outbox[0]
        self.assertIn("VanPere Digital", msg.subject)
        self.assertIn(settings.SITE_URL + "/accounts/reset/", msg.body)
        self.assertEqual(msg.alternatives[0][1], "text/html")
