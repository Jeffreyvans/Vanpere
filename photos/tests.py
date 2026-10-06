import hashlib
import io
import struct
import tempfile
import unittest
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import User
from events import timeutils
from events.models import Event
from storage import get_storage
from .models import Photo, UploadConsent
from .security import device_hash
from .services.image_pipeline import DuplicatePhoto, PhotoRejected, process_photo
from .services.imaging import build_versions

try:
    import pillow_heif
except ImportError:
    pillow_heif = None

TOKEN = "a" * 32


def make_jpeg(size=(800, 600), exif=None, color=(200, 80, 40)):
    buf = io.BytesIO()
    kw = {"exif": exif} if exif else {}
    Image.new("RGB", size, color).save(buf, "JPEG", **kw)
    return buf.getvalue()


def exif_with_gps():
    """Hand-built EXIF block holding a GPS IFD (latitude/longitude refs)."""
    header = b"Exif\x00\x00MM\x00\x2a\x00\x00\x00\x08"
    ifd0 = struct.pack(">H", 1) + struct.pack(">HHII", 0x8825, 4, 1, 26) + struct.pack(">I", 0)
    gps = (struct.pack(">H", 2) + struct.pack(">HHI", 1, 2, 2) + b"N\x00\x00\x00"
           + struct.pack(">HHI", 3, 2, 2) + b"E\x00\x00\x00" + struct.pack(">I", 0))
    return header + ifd0 + gps


class MediaMixin:
    def setUp(self):
        super().setUp()
        cache.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        o = override_settings(MEDIA_ROOT=tmp.name, STORAGE_BACKEND="local")
        o.enable()
        self.addCleanup(o.disable)
        self.owner = User.objects.create_user(
            "o@example.com", "S0meLongPass!9", email_verified=True, is_staff=True, is_superuser=True)
        d = timeutils.local_today() + timedelta(days=5)
        self.event = Event.objects.create(
            owner=self.owner, name="Test", event_date=d, expires_at=timeutils.default_expires_at(d))


class PipelineTests(MediaMixin, TestCase):
    def _photo(self, raw, **kw):
        p = Photo.objects.create(event=self.event, uploader_hash="u", ip_hash="i",
                                 declared_content_type="image/jpeg", **kw)
        get_storage().put(p.upload_key, raw, "image/jpeg")
        return p

    def test_three_versions_sizes_and_usage_counter(self):
        p = process_photo(self._photo(make_jpeg((3000, 2000))).id)
        self.assertEqual(p.status, Photo.Status.APPROVED)
        s = get_storage()
        sizes = {v: Image.open(s.get_stream(p.key(v))).size for v in ("original", "medium", "thumb")}
        self.assertEqual(sizes["original"], (3000, 2000))
        self.assertEqual(max(sizes["medium"]), 1600)
        self.assertEqual(max(sizes["thumb"]), 480)
        self.event.refresh_from_db()
        self.assertEqual(self.event.storage_used_bytes, p.total_bytes)
        self.assertFalse(s.exists(p.upload_key))

    def test_moderation_makes_pending(self):
        self.event.moderation_enabled = True
        self.event.save()
        self.assertEqual(process_photo(self._photo(make_jpeg()).id).status, Photo.Status.PENDING)

    def test_exif_orientation_applied(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        p = process_photo(self._photo(make_jpeg((100, 50), exif=exif.tobytes())).id)
        self.assertEqual((p.width, p.height), (50, 100))

    def test_gps_stripped_from_every_version(self):
        raw = make_jpeg(exif=exif_with_gps())
        self.assertTrue(Image.open(io.BytesIO(raw)).getexif().get_ifd(0x8825), "fixture must contain GPS")
        p = process_photo(self._photo(raw).id)
        for v in ("original", "medium", "thumb"):
            img = Image.open(get_storage().get_stream(p.key(v)))
            exif = img.getexif()
            self.assertNotIn(0x8825, exif)
            self.assertFalse(exif.get_ifd(0x8825))
            self.assertNotIn("exif", img.info)

    @unittest.skipIf(pillow_heif is None, "pillow-heif not installed")
    def test_heic_converted_to_jpeg(self):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), "red").save(buf, "HEIF")
        p = process_photo(self._photo(buf.getvalue()).id)
        self.assertEqual(Image.open(get_storage().get_stream(p.key("original"))).format, "JPEG")

    def test_rejects_non_image_and_oversize_dimensions(self):
        with self.assertRaises(PhotoRejected):
            build_versions(b"not an image at all")
        with self.assertRaises(PhotoRejected):
            process_photo(self._photo(b"%PDF-1.4 fake").id)

    def test_rejects_file_over_event_limit(self):
        self.event.max_upload_size_mb = 1
        self.event.save()
        big = make_jpeg((3000, 3000))
        raw = big + b"\x00" * (1024 * 1024)
        with self.assertRaises(PhotoRejected):
            process_photo(self._photo(raw).id)

    def test_duplicate_content_rejected(self):
        raw = make_jpeg()
        process_photo(self._photo(raw).id)
        with self.assertRaises(DuplicatePhoto):
            process_photo(self._photo(raw).id)


class ApiTests(MediaMixin, TestCase):
    def _post(self, name, data=None, token=TOKEN, **kw):
        url = reverse(f"photos:{name}", kwargs={"code": self.event.public_code, **kw})
        return self.client.post(url, data or {}, content_type="application/json", HTTP_X_DEVICE_TOKEN=token)

    def _consent(self):
        self.assertEqual(self._post("consent").status_code, 200)

    def _init(self, raw, **extra):
        body = {"content_type": "image/jpeg", "size": len(raw),
                "hash": hashlib.sha256(raw).hexdigest(), "name": "Ann"}
        body.update(extra)
        return self._post("init", body)

    def _send_file(self, pid, raw, token=TOKEN):
        url = reverse("photos:file", kwargs={"code": self.event.public_code, "photo_id": pid})
        return self.client.post(url, {"file": SimpleUploadedFile("p.jpg", raw, "image/jpeg")},
                                HTTP_X_DEVICE_TOKEN=token)

    def test_consent_required_and_recorded_without_raw_ip(self):
        raw = make_jpeg()
        self.assertEqual(self._init(raw).status_code, 403)
        self._consent()
        c = UploadConsent.objects.get()
        self.assertEqual(c.device_hash, device_hash(TOKEN))
        self.assertNotIn("127.0.0.1", c.ip_hash)

    def test_full_fallback_flow_and_duplicates(self):
        raw = make_jpeg()
        self._consent()
        h = hashlib.sha256(raw).hexdigest()
        self.assertFalse(self._post("check_hash", {"hash": h}).json()["exists"])
        r = self._init(raw)
        self.assertIsNone(r.json()["upload"])
        pid = r.json()["photo_id"]
        self.assertEqual(self._send_file(pid, raw).status_code, 200)
        fin = self._post("finalise", photo_id=pid)
        self.assertEqual(fin.json()["status"], "approved")
        self.assertTrue(self._post("check_hash", {"hash": h}).json()["exists"])
        self.assertTrue(self._init(raw).json()["duplicate"])

    def test_interrupted_upload_is_resumable(self):
        raw = make_jpeg()
        self._consent()
        first = self._init(raw).json()["photo_id"]
        self.assertEqual(self._init(raw).json()["photo_id"], first)

    def test_other_device_cannot_finalise(self):
        raw = make_jpeg()
        self._consent()
        pid = self._init(raw).json()["photo_id"]
        self._send_file(pid, raw)
        self.assertEqual(self._post("finalise", token="b" * 32, photo_id=pid).status_code, 403)

    def test_non_image_rejected_and_row_removed(self):
        junk = b"%PDF-1.4 not a photo"
        self._consent()
        pid = self._init(junk).json()["photo_id"]
        self._send_file(pid, junk)
        r = self._post("finalise", photo_id=pid)
        self.assertEqual(r.status_code, 422)
        self.assertFalse(Photo.objects.exists())

    def test_validation_errors(self):
        raw = make_jpeg()
        self._consent()
        self.assertEqual(self._init(raw, content_type="application/pdf").status_code, 415)
        self.assertEqual(self._init(raw, size=99 * 1024 * 1024).status_code, 413)
        self.assertEqual(self._init(raw, hash="xyz").status_code, 400)

    def test_batch_limit(self):
        self.event.max_photos_per_upload = 2
        self.event.save()
        self._consent()
        batch = "11111111-1111-4111-8111-111111111111"
        colors = ((220, 30, 40), (40, 180, 60), (30, 40, 200))
        for color in colors[:2]:
            self.assertEqual(self._init(make_jpeg(color=color), batch_id=batch).status_code, 200)
        self.assertEqual(self._init(make_jpeg(color=colors[2]), batch_id=batch).status_code, 400)

    def test_expired_and_disabled_events_block_uploads(self):
        self._consent()
        self.event.allow_uploads = False
        self.event.save()
        self.assertEqual(self._init(make_jpeg()).status_code, 403)
        self.event.allow_uploads = True
        self.event.expires_at = timeutils.end_of_day(timeutils.local_today() - timedelta(days=1))
        self.event.save()
        self.assertEqual(self._init(make_jpeg()).status_code, 410)

    def test_moderation_pending_via_api(self):
        self.event.moderation_enabled = True
        self.event.save()
        raw = make_jpeg()
        self._consent()
        pid = self._init(raw).json()["photo_id"]
        self._send_file(pid, raw)
        self.assertEqual(self._post("finalise", photo_id=pid).json()["status"], "pending")

    @override_settings(UPLOAD_RATE_PER_DEVICE=2)
    def test_rate_limit_per_device(self):
        self._consent()
        codes = [self._init(make_jpeg(color=(i, 1, 1))).status_code for i in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_upload_page_renders(self):
        r = self.client.get(reverse("photos:upload", args=[self.event.public_code]))
        self.assertContains(r, 'data-max-mb="15"')


class GuestNoAccountTests(MediaMixin, TestCase):
    """Guests upload and view with no account: no login, no session user, no extra users created."""

    def setUp(self):
        super().setUp()
        self.code = self.event.public_code

    def _post(self, name, data=None, token=TOKEN, **kw):
        url = reverse(f"photos:{name}", kwargs={"code": self.code, **kw})
        return self.client.post(url, data or {}, content_type="application/json", HTTP_X_DEVICE_TOKEN=token)

    def test_guests_view_upload_and_gallery_without_an_account(self):
        for name, args in (("upload", [self.code]), ("gallery", [self.code]), ("slideshow", [self.code])):
            r = self.client.get(reverse(f"photos:{name}", args=args))
            self.assertEqual(r.status_code, 200, name)
            self.assertNotContains(r, "/accounts/register/")
        self.assertEqual(self.client.get(reverse("photos:photo_list", args=[self.code])).status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 1)  # only the administrator/owner created in setUp

    def test_guests_upload_without_an_account(self):
        raw = make_jpeg()
        self.assertEqual(self._post("consent").status_code, 200)
        h = hashlib.sha256(raw).hexdigest()
        r = self._post("init", {"content_type": "image/jpeg", "size": len(raw),
                                "hash": h, "name": "Ann"})
        pid = r.json()["photo_id"]
        url = reverse("photos:file", kwargs={"code": self.code, "photo_id": pid})
        resp = self.client.post(url, {"file": SimpleUploadedFile("p.jpg", raw, "image/jpeg")},
                                HTTP_X_DEVICE_TOKEN=TOKEN)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._post("finalise", photo_id=pid).json()["status"], "approved")
        photos = self.client.get(reverse("photos:photo_list", args=[self.code])).json()["photos"]
        self.assertEqual(len(photos), 1)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(User.objects.count(), 1)
