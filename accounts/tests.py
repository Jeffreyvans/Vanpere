import re
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

PW = "S0meLongPass!9"


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def _register(self, email="a@example.com"):
        return self.client.post(reverse("accounts:register"), {
            "full_name": "Ann", "email": email, "password1": PW, "password2": PW})

    def test_register_sends_branded_verification(self):
        self.assertRedirects(self._register(), reverse("accounts:home"))
        self.assertFalse(User.objects.get(email="a@example.com").email_verified)
        msg = mail.outbox[0]
        self.assertIn("VanPere Digital", msg.subject)
        self.assertEqual(len(msg.alternatives), 1)

    def test_register_filebased_backend_does_not_raise_oserror(self):
        """Windows consoles raise OSError [Errno 22] on console.EmailBackend.flush."""
        with TemporaryDirectory() as tmp:
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend",
                EMAIL_FILE_PATH=tmp,
            ):
                response = self._register("file@example.com")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse("accounts:home"))
                written = list(Path(tmp).iterdir())
                self.assertTrue(written)
                body = written[0].read_text(encoding="utf-8", errors="replace")
                self.assertIn("VanPere Digital", body)
                self.assertIn("verify", body.lower())

    def test_verify_link_marks_verified(self):
        self._register()
        link = re.search(r"http\S+/accounts/verify/\S+/", mail.outbox[0].body).group(0)
        self.client.get(link[len(settings.SITE_URL):])
        self.assertTrue(User.objects.get(email="a@example.com").email_verified)

    def test_bad_token_rejected(self):
        self.assertEqual(self.client.get(reverse("accounts:verify", args=["bad"])).status_code, 400)

    def test_duplicate_email_case_insensitive(self):
        self._register()
        self.client.logout()
        self._register("A@Example.com")
        self.assertEqual(User.objects.count(), 1)

    def test_resend_cooldown(self):
        self._register()
        self.client.post(reverse("accounts:resend_verification"))
        self.client.post(reverse("accounts:resend_verification"))
        self.assertEqual(len(mail.outbox), 2)  # registration + first resend only


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user("a@example.com", PW)

    def _login(self, email, pw):
        return self.client.post(reverse("accounts:login"), {"username": email, "password": pw})

    def test_email_lockout(self):
        for _ in range(settings.LOGIN_MAX_FAILURES):
            self._login("a@example.com", "wrong")
        r = self._login("a@example.com", PW)
        self.assertContains(r, "Too many failed attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_ip_lockout_across_emails(self):
        for i in range(settings.LOGIN_MAX_FAILURES):
            self._login(f"x{i}@example.com", "wrong")
        self.assertContains(self._login("a@example.com", PW), "Too many failed attempts")

    def test_successful_login(self):
        self._login("A@example.com", PW)
        self.assertIn("_auth_user_id", self.client.session)


class PasswordResetTests(TestCase):
    def test_reset_email_is_branded_html_and_text(self):
        User.objects.create_user("a@example.com", PW)
        self.client.post(reverse("accounts:password_reset"), {"email": "a@example.com"})
        msg = mail.outbox[0]
        self.assertIn("VanPere Digital", msg.subject)
        self.assertIn(settings.SITE_URL + "/accounts/reset/", msg.body)
        self.assertEqual(msg.alternatives[0][1], "text/html")
