from datetime import timedelta
import uuid

from django.test import TestCase
from django.urls import reverse

from events import timeutils
from storage import get_storage
from .models import Photo
from .security import device_hash
from .tests import TOKEN, make_jpeg
from .tests_gallery import GalleryBase


class PhotoLinkTests(GalleryBase):
    def page(self, photo, code=None):
        return self.client.get(reverse("photos:photo", args=[code or self.event.public_code, photo.id]))

    def og(self, photo):
        return self.client.get(reverse("photos:photo_og", args=[self.event.public_code, photo.id]))

    def test_page_has_preview_tags_and_share_buttons(self):
        p = self.make_photo()
        r = self.page(p)
        self.assertContains(r, 'property="og:image"')
        self.assertContains(r, reverse("photos:photo_og", args=[self.event.public_code, p.id]))
        self.assertContains(r, f"/p/{p.id}/")
        self.assertContains(r, "wa.me")
        self.assertContains(r, "noindex")

    def test_unapproved_and_foreign_photos_are_404(self):
        pending = self.make_photo(status=Photo.Status.PENDING)
        self.assertEqual(self.page(pending).status_code, 404)
        self.assertEqual(self.og(pending).status_code, 404)
        approved = self.make_photo()
        self.assertEqual(self.page(approved, code="ZZZZZZZZ").status_code, 404)

    def test_owner_can_open_pending_photo_page(self):
        pending = self.make_photo(status=Photo.Status.PENDING)
        self.client.force_login(self.owner)
        self.assertEqual(self.page(pending).status_code, 200)

    def test_pin_hides_image_and_preview(self):
        p = self.make_photo()
        self.lock_with_pin()
        r = self.page(p)
        self.assertContains(r, 'name="pin"')
        self.assertNotContains(r, "og:image")
        self.assertNotContains(r, "/media/")
        self.assertEqual(self.og(p).status_code, 404)
        self.client.post(reverse("events:pin", args=[self.event.public_code]),
                         {"pin": "4821", "next": reverse("photos:photo", args=[self.event.public_code, p.id])})
        self.assertContains(self.page(p), "/media/")

    def test_expired_event(self):
        p = self.make_photo()
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertContains(self.page(p), "This event has ended")
        self.assertEqual(self.og(p).status_code, 404)

    def test_og_image_served_for_open_event(self):
        r = self.og(self.make_photo())
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/webp"))


class VideoShareTests(GalleryBase):
    def make_video(self, status=Photo.Status.APPROVED, poster=True):
        p = Photo.objects.create(
            event=self.event, uploader_hash=device_hash(TOKEN), ip_hash="i",
            declared_content_type="video/mp4", media_type=Photo.MediaType.VIDEO,
            status=status, width=0, height=0, content_hash=uuid.uuid4().hex * 2,
            original_bytes=100, poster_bytes=50 if poster else 0)
        get_storage().put(p.key("original"), b"fake-mp4", "video/mp4")
        if poster:
            get_storage().put(p.key("poster"), make_jpeg((80, 60)), "image/webp")
        return p

    def page(self, photo, code=None):
        return self.client.get(reverse("photos:photo", args=[code or self.event.public_code, photo.id]))

    def test_video_page_renders_player_and_download(self):
        video = self.make_video()
        r = self.page(video)
        self.assertContains(r, "<video")
        self.assertContains(r, "controls")
        self.assertContains(r, "Download video")
        self.assertContains(r, reverse("photos:photo_download",
                                       args=[self.event.public_code, video.id]))
        self.assertContains(r, "wa.me")

    def test_video_page_without_poster_still_renders(self):
        r = self.page(self.make_video(poster=False))
        self.assertContains(r, "<video")
        self.assertNotContains(r, "poster=")

    def test_pending_and_pin_and_expiry_fail_closed(self):
        pending = self.make_video(status=Photo.Status.PENDING)
        self.assertEqual(self.page(pending).status_code, 404)
        p = self.make_video()
        self.lock_with_pin()
        r = self.page(p)
        self.assertContains(r, 'name="pin"')
        self.assertNotContains(r, "<video")
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertContains(self.page(p), "This event has ended")


class ServiceWorkerTests(TestCase):
    def test_scoped_worker_with_precache(self):
        r = self.client.get("/event/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertEqual(r["Service-Worker-Allowed"], "/event/")
        body = r.content.decode()
        self.assertIn("css/main.css", body)
        self.assertIn("js/upload/uploader", body)
        self.assertIn("/upload/", body)
        precache = body.split("const PRECACHE = ")[1].split(";")[0]
        self.assertNotIn("/api/", precache)
        self.assertNotIn("/media/", precache)

    def test_upload_page_registers_worker(self):
        with open("static/js/upload/uploader.js") as f:
            self.assertIn('register("/event/sw.js", { scope: "/event/" })', f.read())
