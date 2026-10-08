from datetime import timedelta, datetime, timezone as dt_tz
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from photos.tests import make_jpeg
from . import timeutils
from .models import CODE_ALPHABET, Event
from .views import _new_create_token

PW = "S0meLongPass!9"


def make_event(owner, **kw):
    d = timeutils.local_today() + timedelta(days=5)
    defaults = dict(owner=owner, name="Tendai & Rudo", event_date=d, expires_at=timeutils.default_expires_at(d))
    defaults.update(kw)
    return Event.objects.create(**defaults)


class TimeTests(TestCase):
    def test_end_of_day_is_harare(self):
        from datetime import date
        dt = timeutils.end_of_day(date(2026, 3, 1))
        self.assertEqual(dt.utcoffset(), timedelta(hours=2))
        self.assertEqual(dt.astimezone(dt_tz.utc).hour, 21)

    def test_day_boundaries(self):
        from datetime import date
        exp = timeutils.end_of_day(date(2026, 3, 1))
        u = lambda *a: datetime(*a, tzinfo=dt_tz.utc)
        self.assertFalse(timeutils.is_expired(exp, u(2026, 3, 1, 21, 59, 59)))
        self.assertTrue(timeutils.is_expired(exp, u(2026, 3, 1, 22, 0, 0)))
        self.assertEqual(timeutils.days_remaining(exp, u(2026, 2, 28, 21, 59)), 1)
        self.assertEqual(timeutils.days_remaining(exp, u(2026, 2, 28, 22, 0)), 0)
        self.assertEqual(timeutils.days_remaining(exp, u(2026, 3, 5)), 0)


class CodeTests(TestCase):
    def test_codes_unique_unambiguous(self):
        owner = User.objects.create_user("o@example.com", PW)
        codes = {make_event(owner).public_code for _ in range(60)}
        self.assertEqual(len(codes), 60)
        for c in codes:
            self.assertEqual(len(c), 8)
            self.assertTrue(set(c) <= set(CODE_ALPHABET))
            self.assertFalse(set(c) & set("0O1IL"))


class OrganiserTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            "o@example.com", PW, email_verified=True, is_staff=True, is_superuser=True)
        self.other = User.objects.create_user(
            "x@example.com", PW, email_verified=True, is_staff=True, is_superuser=True)

    def _post_data(self, **kw):
        d = timeutils.local_today() + timedelta(days=5)
        data = {"name": "Rudo's 30th", "event_type": "birthday", "event_date": d.isoformat(),
                "expires_on": "", "location": "Harare", "description": "", "allow_uploads": "on",
                "max_upload_size_mb": 15, "max_video_size_mb": 500, "max_photos_per_upload": 20, "pin": ""}
        data.update(kw)
        return d, data

    def test_non_admin_cannot_create(self):
        u = User.objects.create_user("u@example.com", PW)
        self.client.force_login(u)
        _, data = self._post_data()
        r = self.client.post(reverse("events:create"), data)
        self.assertRedirects(r, reverse("accounts:home"))
        self.assertEqual(Event.objects.count(), 0)

    def test_non_admin_cannot_view_or_manage_events(self):
        ev = make_event(self.owner)
        u = User.objects.create_user("u2@example.com", PW, email_verified=True)
        self.client.force_login(u)
        for name, args in (("list", []), ("create", []),
                           ("detail", [ev.pk]), ("edit", [ev.pk]), ("qr_png", [ev.pk])):
            r = self.client.get(reverse(f"events:{name}", args=args))
            self.assertRedirects(r, reverse("accounts:home"), msg_prefix=name)
        self.client.logout()
        for name, args in (("list", []), ("create", []), ("detail", [ev.pk])):
            self.assertEqual(
                self.client.get(reverse(f"events:{name}", args=args)).status_code, 302, name)

    def test_create_default_expiry_pin_hashed_and_email(self):
        self.client.force_login(self.owner)
        d, data = self._post_data(pin="4821")
        r = self.client.post(reverse("events:create"), data)
        ev = Event.objects.get()
        self.assertRedirects(r, reverse("events:detail", args=[ev.pk]))
        self.assertEqual(ev.expires_at, timeutils.default_expires_at(d))
        self.assertNotIn("4821", ev.view_pin_hash)
        self.assertTrue(ev.check_pin("4821"))
        self.assertIn("VanPere Digital", mail.outbox[0].subject)

    def test_owner_scoping(self):
        ev = make_event(self.owner)
        self.client.force_login(self.other)
        for name, args in [("detail", [ev.pk]), ("edit", [ev.pk]), ("qr_png", [ev.pk]),
                           ("qr_svg", [ev.pk]), ("poster", [ev.pk, "a4"])]:
            self.assertEqual(self.client.get(reverse(f"events:{name}", args=args)).status_code, 404, name)

    def test_qr_and_posters(self):
        ev = make_event(self.owner)
        self.client.force_login(self.owner)
        self.assertTrue(self.client.get(reverse("events:qr_png", args=[ev.pk])).content.startswith(b"\x89PNG"))
        self.assertIn(b"<svg", self.client.get(reverse("events:qr_svg", args=[ev.pk])).content)
        for size in ("a4", "a5", "table"):
            r = self.client.get(reverse("events:poster", args=[ev.pk, size]))
            self.assertTrue(r.content.startswith(b"%PDF"), size)
        self.assertEqual(self.client.get(reverse("events:poster", args=[ev.pk, "huge"])).status_code, 404)


class PublicTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            "o@example.com", PW, email_verified=True, is_staff=True, is_superuser=True)

    def test_public_page_og_and_noindex(self):
        ev = make_event(self.owner)
        r = self.client.get(ev.public_path)
        self.assertContains(r, 'property="og:title"')
        self.assertContains(r, "twitter:card")
        self.assertContains(r, "noindex")
        self.assertContains(r, ev.public_url)

    def test_inactive_404_and_expired_state(self):
        ev = make_event(self.owner, is_active=False)
        self.assertEqual(self.client.get(ev.public_path).status_code, 404)
        ev2 = make_event(self.owner, expires_at=timeutils.end_of_day(timeutils.local_today() - timedelta(days=1)))
        self.assertContains(self.client.get(ev2.public_path), "This event has ended")

    def test_pin_flow_and_rate_limit(self):
        ev = make_event(self.owner)
        ev.set_pin("4821")
        ev.save()
        url = reverse("events:pin", args=[ev.public_code])
        self.client.post(url, {"pin": "0000"})
        self.assertNotIn(f"pin_ok:{ev.public_code}", self.client.session)
        self.client.post(url, {"pin": "4821"})
        self.assertTrue(self.client.session[f"pin_ok:{ev.public_code}"])

    def test_pin_lockout(self):
        ev = make_event(self.owner)
        ev.set_pin("4821")
        ev.save()
        url = reverse("events:pin", args=[ev.public_code])
        for _ in range(5):
            self.client.post(url, {"pin": "0000"})
        self.client.post(url, {"pin": "4821"})
        self.assertNotIn(f"pin_ok:{ev.public_code}", self.client.session)


class CreateResilienceTests(TestCase):
    """The event must survive anything that happens after it is saved."""

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            "o@example.com", PW, email_verified=True, is_staff=True, is_superuser=True)
        self.client.force_login(self.owner)

    def _post_data(self, **kw):
        d = timeutils.local_today() + timedelta(days=5)
        data = {"name": "Rudo's 30th", "event_type": "birthday", "event_date": d.isoformat(),
                "expires_on": "", "location": "Harare", "description": "", "allow_uploads": "on",
                "max_upload_size_mb": 15, "max_video_size_mb": 500, "max_photos_per_upload": 20, "pin": ""}
        data.update(kw)
        return d, data

    def test_email_failure_still_creates_and_redirects(self):
        _, data = self._post_data()
        with mock.patch("events.views.send_event_created", side_effect=OSError("smtp down")):
            r = self.client.post(reverse("events:create"), data)
        ev = Event.objects.get()
        self.assertEqual(r.status_code, 302, r.status_code)
        self.assertRedirects(r, reverse("events:detail", args=[ev.pk]))
        self.assertEqual(ev.owner, self.owner)

    def test_double_submission_creates_one_event(self):
        _, data = self._post_data()
        data["submission_token"] = _new_create_token()
        r1 = self.client.post(reverse("events:create"), data)
        r2 = self.client.post(reverse("events:create"), data)
        self.assertEqual(Event.objects.count(), 1)
        ev = Event.objects.get()
        self.assertEqual(r1.status_code, 302)
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(r1["Location"], r2["Location"])
        self.assertEqual(r1["Location"], reverse("events:detail", args=[ev.pk]))

    def test_fresh_token_per_form_render(self):
        t1 = self.client.get(reverse("events:create")).context["submission_token"]
        t2 = self.client.get(reverse("events:create")).context["submission_token"]
        self.assertNotEqual(t1, t2)

    def test_invalid_form_reuses_token(self):
        _, data = self._post_data(name="")
        token = _new_create_token()
        data["submission_token"] = token
        r = self.client.post(reverse("events:create"), data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["submission_token"], token)
        self.assertEqual(Event.objects.count(), 0)

    def test_tampered_token_does_not_block_creation(self):
        _, data = self._post_data()
        data["submission_token"] = "not-a-real-token"
        r = self.client.post(reverse("events:create"), data)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Event.objects.count(), 1)

    def test_cover_upload_failure_still_creates_event(self):
        _, data = self._post_data()
        data["cover"] = SimpleUploadedFile("cover.jpg", make_jpeg((400, 300)), "image/jpeg")
        with mock.patch("events.forms.get_storage", side_effect=OSError("storage down")):
            r = self.client.post(reverse("events:create"), data)
        ev = Event.objects.get()
        self.assertEqual(r.status_code, 302, r.status_code)
        self.assertRedirects(r, reverse("events:detail", args=[ev.pk]))
        self.assertFalse(ev.cover_image)

    def test_edit_cover_upload_failure_does_not_500(self):
        _, data = self._post_data()
        self.client.post(reverse("events:create"), data)
        ev = Event.objects.get()
        _, edit = self._post_data(name="Renamed", cover=SimpleUploadedFile(
            "cover.jpg", make_jpeg((400, 300)), "image/jpeg"))
        with mock.patch("events.forms.get_storage", side_effect=OSError("storage down")):
            r = self.client.post(reverse("events:edit", args=[ev.pk]), edit)
        self.assertEqual(r.status_code, 302, r.status_code)
        ev.refresh_from_db()
        self.assertEqual(ev.name, "Renamed")
        self.assertFalse(ev.cover_image)
