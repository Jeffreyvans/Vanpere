from datetime import date, datetime, timedelta, timezone as dt_tz
from io import StringIO

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from events import timeutils
from events.expiry import run_expiry
from events.forms import EventForm
from events.models import Event
from photos.models import Photo, UploadConsent
from photos.security import device_hash
from photos.services.cleanup import cleanup_orphans
from photos.tests import MediaMixin, TOKEN, make_jpeg
from storage import get_storage


def at(m, d, h=10):
    return datetime(2026, m, d, h, tzinfo=dt_tz.utc)


class OpsBase(MediaMixin, TestCase):
    def set_expiry(self, d):
        Event.objects.filter(pk=self.event.pk).update(expires_at=timeutils.end_of_day(d))
        self.event.refresh_from_db()

    def make_photo(self, status=Photo.Status.APPROVED):
        p = Photo.objects.create(event=self.event, uploader_hash=device_hash(TOKEN), ip_hash="i",
                                 declared_content_type="image/jpeg", status=status, width=80, height=60,
                                 original_bytes=100, medium_bytes=100, thumb_bytes=100)
        for v in ("original", "medium", "thumb", "upload"):
            get_storage().put(p.key(v) if v != "upload" else p.upload_key, make_jpeg((80, 60)), "image/jpeg")
        return p


class ExpiryTests(OpsBase):
    def test_marks_expired_once(self):
        self.set_expiry(date(2026, 6, 5))
        self.assertEqual(run_expiry(now=at(6, 6))["marked"], 1)
        self.event.refresh_from_db()
        self.assertIsNotNone(self.event.expiry_marked_at)
        self.assertEqual(run_expiry(now=at(6, 6))["marked"], 0)

    def test_warnings_sent_once_per_threshold(self):
        self.set_expiry(date(2026, 6, 5))
        self.assertEqual(run_expiry(now=at(6, 1))["warned"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("VanPere Digital", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertEqual(run_expiry(now=at(6, 1))["warned"], 0)
        self.assertEqual(run_expiry(now=at(6, 4))["warned"], 1)
        self.assertEqual(run_expiry(now=at(6, 4))["warned"], 0)
        self.assertEqual(len(mail.outbox), 2)
        self.event.refresh_from_db()
        self.assertEqual(self.event.warned_days, [7, 1])

    def test_no_warning_after_expiry(self):
        self.set_expiry(date(2026, 6, 5))
        self.assertEqual(run_expiry(now=at(6, 6))["warned"], 0)
        self.assertEqual(mail.outbox, [])

    def test_purge_after_grace_keeps_minimal_metadata(self):
        p = self.make_photo()
        UploadConsent.objects.create(event=self.event, device_hash="d", ip_hash="i")
        Event.objects.filter(pk=self.event.pk).update(storage_used_bytes=300)
        self.set_expiry(date(2026, 6, 5))
        self.assertEqual(run_expiry(now=at(6, 19))["purged"], 0)  # still inside the 14-day grace
        self.assertTrue(get_storage().exists(p.key("original")))
        self.assertEqual(run_expiry(now=at(6, 20), dry_run=True)["purged"], 1)
        self.assertTrue(Photo.objects.exists())  # dry run changed nothing
        self.assertEqual(run_expiry(now=at(6, 20))["purged"], 1)
        self.event.refresh_from_db()
        self.assertFalse(Photo.objects.exists() or UploadConsent.objects.exists())
        self.assertFalse(get_storage().exists(p.key("original")))
        self.assertIsNotNone(self.event.files_purged_at)
        self.assertEqual((self.event.storage_used_bytes, self.event.cover_image), (0, ""))
        self.assertEqual(run_expiry(now=at(6, 21))["purged"], 0)  # idempotent

    def test_changing_expiry_resets_warnings(self):
        Event.objects.filter(pk=self.event.pk).update(warned_thresholds="7,1", expiry_marked_at=at(6, 1))
        self.event.refresh_from_db()
        form = EventForm({"name": "X", "event_type": "other", "event_date": self.event.event_date.isoformat(),
                          "expires_on": (self.event.event_date + timedelta(days=10)).isoformat(), "location": "",
                          "description": "", "allow_uploads": "on", "max_upload_size_mb": 15,
                          "max_photos_per_upload": 20, "pin": ""}, instance=self.event)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual((saved.warned_thresholds, saved.expiry_marked_at), ("", None))

    def test_purged_event_cannot_be_reopened_and_command_reports(self):
        Event.objects.filter(pk=self.event.pk).update(files_purged_at=at(6, 20))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("events:edit", args=[self.event.pk])).status_code, 302)
        out = StringIO()
        call_command("expire_events", "--dry-run", stdout=out)
        self.assertIn("expire_events: marked=", out.getvalue())


class CleanupTests(OpsBase):
    def test_only_stale_unfinalised_uploads_removed(self):
        stale = self.make_photo(Photo.Status.UPLOADING)
        fresh = self.make_photo(Photo.Status.UPLOADING)
        old_ok = self.make_photo(Photo.Status.APPROVED)
        Photo.objects.filter(pk__in=[stale.pk, old_ok.pk]).update(created_at=at(1, 1))
        self.assertEqual(cleanup_orphans(now=at(1, 3), dry_run=True)["removed"], 1)
        self.assertTrue(Photo.objects.filter(pk=stale.pk).exists())
        Photo.objects.filter(pk=fresh.pk).update(created_at=at(1, 3))
        self.assertEqual(cleanup_orphans(now=at(1, 3, 11))["removed"], 1)
        self.assertEqual(set(Photo.objects.values_list("pk", flat=True)), {fresh.pk, old_ok.pk})
        self.assertFalse(get_storage().exists(stale.upload_key))
        out = StringIO()
        call_command("cleanup_orphans", stdout=out)
        self.assertIn("cleanup_orphans: removed=", out.getvalue())


class SeedDemoTests(OpsBase):
    def test_seed_is_guarded_and_idempotent(self):
        with self.assertRaises(CommandError):  # tests run with DEBUG off
            call_command("seed_demo")
        call_command("seed_demo", force=True, stdout=StringIO())
        call_command("seed_demo", force=True, stdout=StringIO())
        demo = Event.objects.get(name__contains="(demo)")
        self.assertEqual(demo.photos.filter(status="approved").count(), 8)
        self.assertEqual(User.objects.filter(email="demo@example.com").count(), 1)
        self.assertTrue(get_storage().exists(demo.photos.first().key("thumb")))
