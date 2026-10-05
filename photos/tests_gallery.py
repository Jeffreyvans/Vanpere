import time
import uuid

from django.core import signing
from django.test import TestCase
from django.urls import reverse

from events import timeutils
from events.models import Event
from storage import get_storage
from .models import Photo, Report
from .security import device_hash
from .tests import MediaMixin, TOKEN, make_jpeg
from datetime import timedelta


class GalleryBase(MediaMixin, TestCase):
    def make_photo(self, status=Photo.Status.APPROVED, token=TOKEN):
        p = Photo.objects.create(
            event=self.event, uploader_hash=device_hash(token), ip_hash="i", declared_content_type="image/jpeg",
            status=status, width=800, height=600, content_hash=uuid.uuid4().hex * 2,
            original_bytes=100, medium_bytes=100, thumb_bytes=100)
        for v in ("original", "medium", "thumb"):
            get_storage().put(p.key(v), make_jpeg((80, 60)), "image/jpeg")
        Event.objects.filter(pk=self.event.pk).update(storage_used_bytes=self.event.storage_used_bytes + 300)
        self.event.refresh_from_db()
        return p

    def url(self, name, **kw):
        return reverse(f"photos:{name}", kwargs={"code": self.event.public_code, **kw})

    def post(self, name, data=None, token=TOKEN, **kw):
        return self.client.post(self.url(name, **kw), data or {}, content_type="application/json",
                                HTTP_X_DEVICE_TOKEN=token)

    def lock_with_pin(self):
        self.event.set_pin("4821")
        self.event.save()


class ListTests(GalleryBase):
    def test_only_approved_visible_and_mine_flag(self):
        a = self.make_photo()
        for st in (Photo.Status.PENDING, Photo.Status.REJECTED, Photo.Status.UPLOADING):
            self.make_photo(status=st)
        data = self.client.get(self.url("photo_list"), HTTP_X_DEVICE_TOKEN=TOKEN).json()
        self.assertEqual([p["id"] for p in data["photos"]], [str(a.id)])
        self.assertTrue(data["photos"][0]["mine"])
        other = self.client.get(self.url("photo_list"), HTTP_X_DEVICE_TOKEN="b" * 32).json()
        self.assertFalse(other["photos"][0]["mine"])

    def test_keyset_pagination_no_duplicates(self):
        ids = {str(self.make_photo().id) for _ in range(5)}
        seen, cursor = [], None
        for _ in range(5):
            url = self.url("photo_list") + "?limit=2" + (f"&cursor={cursor}" if cursor else "")
            data = self.client.get(url).json()
            seen += [p["id"] for p in data["photos"]]
            cursor = data["next"]
            if not cursor:
                break
        self.assertEqual(len(seen), 5)
        self.assertEqual(set(seen), ids)

    def test_pin_enforced_on_list_slideshow_and_download(self):
        p = self.make_photo()
        self.lock_with_pin()
        for name, kw in (("photo_list", {}), ("slideshow_data", {}), ("photo_download", {"photo_id": p.id})):
            r = self.client.get(self.url(name, **kw))
            self.assertEqual(r.status_code, 403, name)
        self.client.post(reverse("events:pin", args=[self.event.public_code]), {"pin": "4821"})
        self.assertEqual(self.client.get(self.url("photo_list")).status_code, 200)

    def test_owner_bypasses_pin_and_expiry(self):
        self.make_photo()
        self.lock_with_pin()
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertEqual(self.client.get(self.url("photo_list")).status_code, 410)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url("photo_list")).status_code, 200)


class ActionTests(GalleryBase):
    def test_guest_delete_own_only(self):
        p = self.make_photo()
        self.assertEqual(self.post("photo_delete", photo_id=p.id, token="b" * 32).status_code, 403)
        self.assertEqual(self.post("photo_delete", photo_id=p.id).status_code, 200)
        self.assertFalse(Photo.objects.exists())
        self.assertFalse(get_storage().exists(p.key("thumb")))
        self.event.refresh_from_db()
        self.assertEqual(self.event.storage_used_bytes, 0)

    def test_report_dedupes_and_auto_hides_at_threshold(self):
        p = self.make_photo()
        self.assertEqual(self.post("photo_report", {"reason": "bogus"}, photo_id=p.id).status_code, 400)
        for tok in ("r1" * 16, "r1" * 16, "r2" * 16):
            self.assertEqual(self.post("photo_report", {"reason": "spam"}, token=tok, photo_id=p.id).status_code, 200)
        self.assertEqual(Report.objects.count(), 2)
        p.refresh_from_db()
        self.assertEqual(p.status, Photo.Status.APPROVED)
        r = self.post("photo_report", {"reason": "privacy", "note": "x"}, token="r3" * 16, photo_id=p.id)
        self.assertTrue(r.json()["hidden"])
        p.refresh_from_db()
        self.assertEqual(p.status, Photo.Status.PENDING)
        self.assertEqual(self.client.get(self.url("photo_list")).json()["photos"], [])

    def test_download_medium_for_guest_original_when_allowed_or_owner(self):
        p = self.make_photo()

        def key_of(resp):
            return signing.loads(resp["Location"].strip("/").split("/")[-1], salt="media")["k"]

        r = self.client.get(self.url("photo_download", photo_id=p.id))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(key_of(r).endswith("medium.jpg"))
        served = self.client.get(r["Location"])
        self.assertEqual(served.status_code, 200)
        self.assertIn("attachment", served["Content-Disposition"])
        self.event.allow_downloads = True
        self.event.save()
        self.assertTrue(key_of(self.client.get(self.url("photo_download", photo_id=p.id))).endswith("original.jpg"))
        self.event.allow_downloads = False
        self.event.save()
        self.client.force_login(self.owner)
        self.assertTrue(key_of(self.client.get(self.url("photo_download", photo_id=p.id))).endswith("original.jpg"))


class MediaTests(GalleryBase):
    def test_approved_served_pending_hidden_from_guests(self):
        ok, pending = self.make_photo(), self.make_photo(status=Photo.Status.PENDING)
        s = get_storage()
        self.assertEqual(self.client.get(s.url(ok.key("thumb"))).status_code, 200)
        self.assertEqual(self.client.get(s.url(pending.key("thumb"))).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(s.url(pending.key("thumb"))).status_code, 200)

    def test_bad_expired_and_non_photo_tokens(self):
        p = self.make_photo()
        s = get_storage()
        self.assertEqual(self.client.get("/media/garbage/").status_code, 404)
        old = signing.dumps({"k": p.key("thumb"), "d": None, "e": int(time.time()) - 5}, salt="media")
        self.assertEqual(self.client.get(f"/media/{old}/").status_code, 404)
        cover = signing.dumps({"k": f"events/{self.event.id}/cover.jpg", "d": None, "e": int(time.time()) + 99}, salt="media")
        self.assertEqual(self.client.get(f"/media/{cover}/").status_code, 404)
        self.assertEqual(self.client.get(s.url(p.key("thumb")) + "x").status_code, 404)

    def test_pin_and_expiry_enforced_on_file_urls(self):
        p = self.make_photo()
        url = get_storage().url(p.key("thumb"))
        self.lock_with_pin()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.post(reverse("events:pin", args=[self.event.public_code]), {"pin": "4821"})
        self.assertEqual(self.client.get(url).status_code, 200)
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertEqual(self.client.get(url).status_code, 404)


class PageTests(GalleryBase):
    def test_gallery_and_slideshow_pages(self):
        self.assertContains(self.client.get(self.url("gallery")), 'id="gallery"')
        r = self.client.get(self.url("slideshow") + "?interval=99")
        self.assertContains(r, "data:image/svg+xml;base64,")
        self.assertContains(r, 'data-interval="30"')

    def test_pin_form_shown_with_next(self):
        self.lock_with_pin()
        r = self.client.get(self.url("gallery"))
        self.assertContains(r, 'name="next"')
        self.assertNotContains(r, 'id="gallery"')
        post = self.client.post(reverse("events:pin", args=[self.event.public_code]),
                                {"pin": "4821", "next": self.url("gallery").replace("/api", "")})
        self.assertEqual(post.status_code, 302)
