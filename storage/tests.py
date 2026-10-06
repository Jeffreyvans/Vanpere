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
from unittest import mock  # noqa: E402

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

FILEBASE = "https://s3.filebase.io"

FILEBASE_SETTINGS = dict(
    STORAGE_BACKEND="s3", S3_BUCKET="vanpere", S3_ENDPOINT_URL=FILEBASE,
    S3_REGION="auto", S3_ACCESS_KEY_ID="AKIAEXAMPLE", S3_SECRET_ACCESS_KEY="secret",
    S3_ADDRESSING_STYLE="path", S3_SIGNATURE_VERSION="s3v4")


@unittest.skipUnless(importlib.util.find_spec("boto3"), "boto3 not installed")
@override_settings(**FILEBASE_SETTINGS)
class S3PresignTests(SimpleTestCase):
    def test_presigned_put_targets_filebase_with_s3v4(self):
        d = get_storage().presign_upload("events/a/b/upload.bin", "image/jpeg", 1000)
        self.assertEqual(d["method"], "PUT")
        self.assertTrue(d["url"].startswith("https://s3.filebase.io/vanpere/events/a/b/upload.bin?"))
        self.assertIn("X-Amz-Algorithm=AWS4-HMAC-SHA256", d["url"])
        self.assertIn("X-Amz-Signature", d["url"])
        self.assertIn("X-Amz-Expires=600", d["url"])
        self.assertIn("%2Fauto%2Fs3%2F", d["url"])  # signing region "auto"
        self.assertEqual(d["headers"], {"Content-Type": "image/jpeg"})

    def test_presigned_get_is_private_and_expires(self):
        url = get_storage().url("events/a/b/original.jpg", expires=3600)
        self.assertTrue(url.startswith("https://s3.filebase.io/vanpere/events/a/b/original.jpg?"))
        self.assertIn("X-Amz-Expires=3600", url)
        self.assertIn("X-Amz-Signature", url)

    def test_download_url_sets_filename(self):
        url = get_storage().url("events/a/b/original.jpg", download_name="x.jpg")
        self.assertIn("response-content-disposition", url)
        self.assertIn("X-Amz-Signature", url)

    def test_client_is_wired_to_filebase(self):
        s = get_storage()
        self.assertEqual(s.bucket, "vanpere")
        self.assertEqual(s.client.meta.endpoint_url, FILEBASE)
        self.assertEqual(s.client.meta.region_name, "auto")

    def test_missing_bucket_raises_clear_error(self):
        with override_settings(S3_BUCKET=""):
            with self.assertRaises(ImproperlyConfigured):
                get_storage()

    def test_missing_credentials_raise_clear_error(self):
        with override_settings(S3_ACCESS_KEY_ID="", S3_SECRET_ACCESS_KEY=""):
            with self.assertRaises(ImproperlyConfigured):
                get_storage()


@unittest.skipUnless(importlib.util.find_spec("boto3"), "boto3 not installed")
@override_settings(**FILEBASE_SETTINGS)
class S3ClientCallTests(SimpleTestCase):
    """boto3 is mocked: no credentials or network are used."""

    def _storage(self, client):
        with mock.patch("storage.s3.boto3.client", return_value=client):
            return get_storage()

    def test_delete_targets_bucket_and_key(self):
        client = mock.MagicMock()
        self._storage(client).delete("events/a/b/x.jpg")
        client.delete_object.assert_called_once_with(Bucket="vanpere", Key="events/a/b/x.jpg")

    def test_put_uploads_bytes_with_content_type(self):
        client = mock.MagicMock()
        self._storage(client).put("events/a/b/x.jpg", b"data", "image/jpeg")
        client.put_object.assert_called_once_with(
            Bucket="vanpere", Key="events/a/b/x.jpg", Body=b"data", ContentType="image/jpeg")

    def test_exists_uses_head_object(self):
        client = mock.MagicMock()
        self.assertTrue(self._storage(client).exists("events/a/b/x.jpg"))
        client.head_object.assert_called_once_with(Bucket="vanpere", Key="events/a/b/x.jpg")
        client.exceptions.ClientError = Exception
        client.head_object.side_effect = Exception("404")
        self.assertFalse(self._storage(client).exists("events/a/b/missing.jpg"))

    def test_delete_prefix_lists_and_deletes(self):
        client = mock.MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "events/a/b/1.jpg"}, {"Key": "events/a/b/2.jpg"}]}]
        self._storage(client).delete_prefix("events/a/b")
        client.delete_objects.assert_called_once_with(
            Bucket="vanpere", Delete={"Objects": [{"Key": "events/a/b/1.jpg"}, {"Key": "events/a/b/2.jpg"}]})
