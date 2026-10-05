import tempfile

from django.test import SimpleTestCase, override_settings

from . import get_storage
from .local import LocalPhotoStorage


class LocalStorageTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.override = override_settings(MEDIA_ROOT=tmp.name, STORAGE_BACKEND="local")
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.s = get_storage()

    def test_factory_returns_local(self):
        self.assertIsInstance(self.s, LocalPhotoStorage)

    def test_put_get_exists_delete(self):
        self.s.put("events/a/b/x.jpg", b"data", "image/jpeg")
        self.assertTrue(self.s.exists("events/a/b/x.jpg"))
        with self.s.get_stream("events/a/b/x.jpg") as f:
            self.assertEqual(f.read(), b"data")
        self.s.delete("events/a/b/x.jpg")
        self.assertFalse(self.s.exists("events/a/b/x.jpg"))

    def test_delete_prefix(self):
        self.s.put("events/a/b/1.jpg", b"1", "image/jpeg")
        self.s.put("events/a/b/2.jpg", b"2", "image/jpeg")
        self.s.delete_prefix("events/a/b")
        self.assertFalse(self.s.exists("events/a/b/1.jpg") or self.s.exists("events/a/b/2.jpg"))

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.s.put("../escape.jpg", b"x", "image/jpeg")

    def test_no_presign_for_local(self):
        self.assertIsNone(self.s.presign_upload("k", "image/jpeg", 100))


import importlib.util  # noqa: E402
import unittest  # noqa: E402


@unittest.skipUnless(importlib.util.find_spec("boto3"), "boto3 not installed")
@override_settings(STORAGE_BACKEND="s3", S3_BUCKET="bkt", S3_ENDPOINT_URL="https://acc.r2.cloudflarestorage.com",
                   S3_REGION="auto", S3_ACCESS_KEY_ID="AKIAEXAMPLE", S3_SECRET_ACCESS_KEY="secret",
                   S3_ADDRESSING_STYLE="path")
class S3PresignTests(SimpleTestCase):
    def test_presigned_put_is_restricted_and_short_lived(self):
        d = get_storage().presign_upload("events/a/b/upload.bin", "image/jpeg", 1000)
        self.assertEqual(d["method"], "PUT")
        self.assertTrue(d["url"].startswith("https://acc.r2.cloudflarestorage.com/bkt/events/a/b/upload.bin?"))
        self.assertIn("X-Amz-Signature", d["url"])
        self.assertIn("X-Amz-Expires=600", d["url"])
        self.assertEqual(d["headers"], {"Content-Type": "image/jpeg"})

    def test_download_url_sets_filename(self):
        url = get_storage().url("events/a/b/original.jpg", download_name="x.jpg")
        self.assertIn("response-content-disposition", url)
