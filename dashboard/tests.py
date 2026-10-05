import io
import uuid
import zipfile

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from events.models import Event
from photos.models import Photo, Report
from photos.security import device_hash
from photos.tests import MediaMixin, TOKEN, make_jpeg
from storage import get_storage

S = Photo.Status
PW = "S0meLongPass!9"


class DashBase(MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)
        self.other = User.objects.create_user("x@example.com", PW, email_verified=True)

    def make_photo(self, status=S.APPROVED, token=TOKEN, name=""):
        p = Photo.objects.create(
            event=self.event, uploader_hash=device_hash(token), ip_hash="i", declared_content_type="image/jpeg",
            status=status, width=80, height=60, uploader_name=name, content_hash=uuid.uuid4().hex * 2,
            original_bytes=100, medium_bytes=100, thumb_bytes=100)
        for v in ("original", "medium", "thumb"):
            get_storage().put(p.key(v), make_jpeg((80, 60)), "image/jpeg")
        Event.objects.filter(pk=self.event.pk).update(storage_used_bytes=self.event.storage_used_bytes + 300)
        self.event.refresh_from_db()
        return p

    def url(self, name, **kw):
        return reverse(f"dashboard:{name}", kwargs={"pk": self.event.pk, **kw})

    def bulk(self, action, photos, **extra):
        return self.client.post(self.url("bulk"), {"action": action, "ids": [str(p.id) for p in photos], **extra})


class ScopingTests(DashBase):
    def test_other_organiser_gets_404_everywhere(self):
        p = self.make_photo()
        self.client.force_login(self.other)
        gets = ["event", "photos", "review", "reports", "contributors", "download_zip", "regenerate", "delete"]
        for name in gets:
            self.assertEqual(self.client.get(self.url(name)).status_code, 404, name)
        posts = [("bulk", {"action": "delete", "ids": [str(p.id)]}), ("contributor_remove", {"device": p.uploader_hash}),
                 ("regenerate", {"confirm": "yes"}), ("delete", {"confirm": "yes"})]
        for name, data in posts:
            self.assertEqual(self.client.post(self.url(name), data).status_code, 404, name)
        self.assertEqual(self.client.post(self.url("toggle", field="moderation_enabled")).status_code, 404)
        self.assertEqual(self.client.post(self.url("report_action", photo_id=p.id), {"action": "delete"}).status_code, 404)
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists() and Photo.objects.filter(pk=p.pk).exists())
        self.assertNotContains(self.client.get(reverse("dashboard:overview")), self.event.name)

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("dashboard:overview")).status_code, 302)


class OverviewTests(DashBase):
    def test_cards_and_quota_warning(self):
        self.make_photo(name="Ann")
        self.make_photo(status=S.PENDING, token="b" * 32)
        self.make_photo(status=S.UPLOADING)
        r = self.client.get(reverse("dashboard:overview"))
        self.assertEqual(r.context["total_photos"], 2)
        self.assertEqual(r.context["events"][0].n_contributors, 2)
        self.assertEqual(r.context["events"][0].n_pending, 1)
        self.assertNotContains(r, "quota exceeded")
        Event.objects.filter(pk=self.event.pk).update(storage_used_bytes=5 * 1024 * 1024)
        with override_settings(ORGANISER_QUOTA_MB=1):
            self.assertContains(self.client.get(reverse("dashboard:overview")), "quota exceeded")

    def test_event_page_stats(self):
        self.make_photo()
        r = self.client.get(self.url("event"))
        self.assertEqual(r.context["stats"]["photos"], 1)
        self.assertEqual(r.context["stats"]["contributors"], 1)


class ModerationTests(DashBase):
    def test_tabs_show_only_their_status(self):
        pend, appr = self.make_photo(S.PENDING), self.make_photo(S.APPROVED)
        rej = self.make_photo(S.REJECTED)
        for tab, expected in (("pending", pend), ("approved", appr), ("rejected", rej)):
            r = self.client.get(self.url("photos") + f"?tab={tab}")
            self.assertEqual([p.id for p in r.context["page"]], [expected.id], tab)

    def test_bulk_approve_reject_restore_delete(self):
        a, b = self.make_photo(S.PENDING), self.make_photo(S.PENDING)
        self.bulk("approve", [a])
        a.refresh_from_db()
        self.assertEqual(a.status, S.APPROVED)
        self.bulk("reject", [b], reason="Blurry")
        b.refresh_from_db()
        self.assertEqual((b.status, b.rejected_reason), (S.REJECTED, "Blurry"))
        self.bulk("restore", [b])
        b.refresh_from_db()
        self.assertEqual((b.status, b.rejected_reason), (S.APPROVED, ""))
        self.bulk("delete", [a, b])
        self.assertFalse(Photo.objects.exists())
        self.assertFalse(get_storage().exists(a.key("original")))
        self.event.refresh_from_db()
        self.assertEqual(self.event.storage_used_bytes, 0)

    def test_pending_hidden_from_guests_until_approved(self):
        p = self.make_photo(S.PENDING)
        guest = self.client_class()
        url = reverse("photos:photo_list", args=[self.event.public_code])
        self.assertEqual(guest.get(url).json()["photos"], [])
        self.bulk("approve", [p])
        self.assertEqual(len(guest.get(url).json()["photos"]), 1)

    def test_set_cover_requires_one_approved_photo(self):
        a, b = self.make_photo(), self.make_photo()
        self.bulk("cover", [a, b])
        self.event.refresh_from_db()
        self.assertEqual(self.event.cover_image, "")
        self.bulk("cover", [a])
        self.event.refresh_from_db()
        self.assertTrue(get_storage().exists(self.event.cover_image))

    def test_contributor_filter_and_review_mode(self):
        self.make_photo(S.PENDING, name="Ann")
        second = self.make_photo(S.PENDING, name="Bob", token="b" * 32)
        r = self.client.get(self.url("photos") + "?tab=pending&q=bob")
        self.assertEqual([p.id for p in r.context["page"]], [second.id])
        r = self.client.get(self.url("review"))
        self.assertEqual(r.context["total"], 2)
        self.bulk("approve", [r.context["photo"]])
        self.assertEqual(self.client.get(self.url("review")).context["total"], 1)

    def test_toggle_moderation(self):
        self.client.post(self.url("toggle", field="moderation_enabled"))
        self.event.refresh_from_db()
        self.assertTrue(self.event.moderation_enabled)
        self.client.post(self.url("toggle", field="public_code"))
        self.assertEqual(Event.objects.get().public_code, self.event.public_code)


class ReportTests(DashBase):
    def _report(self, p, n=1):
        for i in range(n):
            Report.objects.create(photo=p, reason="spam", reporter_hash=f"h{i}" * 8)

    def test_queue_lists_flagged_photo_with_count(self):
        p = self.make_photo()
        self._report(p, 2)
        r = self.client.get(self.url("reports"))
        self.assertEqual(r.context["photos"][0].n_reports, 2)

    def test_dismiss_restores_auto_hidden(self):
        p = self.make_photo(S.PENDING)
        Photo.objects.filter(pk=p.pk).update(auto_hidden=True)
        self._report(p, 3)
        self.client.post(self.url("report_action", photo_id=p.id), {"action": "dismiss"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.auto_hidden), (S.APPROVED, False))
        self.assertFalse(Report.objects.filter(dismissed=False).exists())

    def test_hide_and_delete(self):
        a, b = self.make_photo(), self.make_photo()
        self._report(a)
        self._report(b)
        self.client.post(self.url("report_action", photo_id=a.id), {"action": "hide"})
        a.refresh_from_db()
        self.assertEqual(a.status, S.REJECTED)
        self.client.post(self.url("report_action", photo_id=b.id), {"action": "delete"})
        self.assertFalse(Photo.objects.filter(pk=b.pk).exists())
        self.assertFalse(get_storage().exists(b.key("thumb")))


class ContributorTests(DashBase):
    def test_grouping_and_removal(self):
        self.make_photo(name="Ann")
        self.make_photo(name="Ann")
        keep = self.make_photo(token="b" * 32)
        rows = {r["name"]: r["n"] for r in self.client.get(self.url("contributors")).context["rows"]}
        self.assertEqual(rows, {"Ann": 2, "Anonymous": 1})
        self.client.post(self.url("contributor_remove"), {"device": device_hash(TOKEN)})
        self.assertEqual(list(Photo.objects.values_list("id", flat=True)), [keep.id])


class ZipTests(DashBase):
    def test_zip_has_only_approved_originals_and_is_valid(self):
        self.make_photo()
        self.make_photo()
        self.make_photo(S.PENDING)
        r = self.client.get(self.url("download_zip"))
        data = b"".join(r.streaming_content)
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        self.assertEqual(len(z.namelist()), 2)
        self.assertIn("attachment", r["Content-Disposition"])

    def test_cap_and_empty(self):
        self.assertEqual(self.client.get(self.url("download_zip")).status_code, 302)
        self.make_photo()
        self.make_photo()
        with override_settings(ZIP_MAX_PHOTOS=1):
            r = self.client.get(self.url("download_zip"), follow=True)
        self.assertContains(r, "ZIP limit")


class DangerTests(DashBase):
    def test_regenerate_needs_confirmation_and_invalidates_old_code(self):
        old = self.event.public_path
        self.client.post(self.url("regenerate"))
        self.event.refresh_from_db()
        self.assertEqual(self.event.public_path, old)
        self.client.post(self.url("regenerate"), {"confirm": "yes"})
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.public_path, old)
        self.assertEqual(self.client.get(old).status_code, 404)
        self.assertEqual(self.client.get(self.event.public_path).status_code, 200)

    def test_delete_event_removes_files_and_rows(self):
        p = self.make_photo()
        self.client.post(self.url("delete"))
        self.assertTrue(Event.objects.exists())
        self.client.post(self.url("delete"), {"confirm": "yes"})
        self.assertFalse(Event.objects.exists() or Photo.objects.exists())
        self.assertFalse(get_storage().exists(p.key("original")))
