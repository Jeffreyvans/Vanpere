from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from .s3env import s3_env


class SecurityHeaderTests(TestCase):
    def test_csp_on_public_pages_not_admin(self):
        csp = self.client.get("/")["Content-Security-Policy"]
        for part in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "script-src 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("Content-Security-Policy", self.client.get("/admin/login/"))

    @override_settings(STORAGE_BACKEND="s3", S3_BUCKET="vanpere", S3_ENDPOINT_URL="https://s3.filebase.io")
    def test_csp_allows_bucket_for_images_and_uploads(self):
        csp = self.client.get("/")["Content-Security-Policy"]
        for origin in ("https://s3.filebase.io", "https://vanpere.s3.filebase.io"):
            self.assertEqual(csp.count(origin), 2, origin)  # img-src and connect-src

    def test_healthz_and_robots(self):
        self.assertEqual(self.client.get("/healthz/").content, b"ok")
        robots = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /event/", robots)
        self.assertIn("Disallow: /dashboard/", robots)


class S3EnvironmentTests(SimpleTestCase):
    """config.s3env: Filebase wiring, AWS_* precedence and placeholder rejection."""

    FILEBASE = {
        "AWS_S3_ENDPOINT_URL": "https://s3.filebase.io",
        "AWS_STORAGE_BUCKET_NAME": "vanpere",
        "AWS_S3_REGION_NAME": "auto",
        "AWS_S3_SIGNATURE_VERSION": "s3v4",
        "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "secret",
    }

    def test_filebase_defaults(self):
        d = s3_env(dict(self.FILEBASE))
        self.assertEqual(d["endpoint"], "https://s3.filebase.io")
        self.assertEqual(d["bucket"], "vanpere")
        self.assertEqual(d["region"], "auto")
        self.assertEqual(d["signature_version"], "s3v4")
        self.assertEqual(d["addressing_style"], "path")  # custom endpoint, nothing else set
        self.assertEqual(d["access_key_id"], "AKIDEXAMPLE")
        self.assertEqual(d["secret_access_key"], "secret")

    def test_aws_names_win_over_legacy_s3_names(self):
        env = dict(self.FILEBASE, S3_BUCKET="legacy-bucket",
                   S3_ENDPOINT_URL="https://legacy.example.com", S3_REGION="eu-west-1",
                   S3_ACCESS_KEY_ID="legacy", S3_SECRET_ACCESS_KEY="legacy")
        d = s3_env(env)
        self.assertEqual(d["endpoint"], "https://s3.filebase.io")
        self.assertEqual(d["bucket"], "vanpere")
        self.assertEqual(d["region"], "auto")
        self.assertEqual(d["access_key_id"], "AKIDEXAMPLE")

    def test_legacy_s3_names_still_work(self):
        env = {"S3_ENDPOINT_URL": "https://s3.filebase.io", "S3_BUCKET": "vanpere",
               "S3_REGION": "auto", "S3_ACCESS_KEY_ID": "k", "S3_SECRET_ACCESS_KEY": "s",
               "S3_ADDRESSING_STYLE": "path"}
        d = s3_env(env)
        self.assertEqual(d["endpoint"], "https://s3.filebase.io")
        self.assertEqual(d["bucket"], "vanpere")
        self.assertEqual(d["region"], "auto")
        self.assertEqual(d["addressing_style"], "path")

    def test_r2_placeholder_endpoint_is_never_returned(self):
        for value in ("YOUR_R2_ENDPOINT", "your_r2_endpoint", "<ACCOUNT_ID>.r2.cloudflarestorage.com",
                      "change-me", "placeholder", "", "   ", "None"):
            d = s3_env({"AWS_S3_ENDPOINT_URL": value, "AWS_STORAGE_BUCKET_NAME": "vanpere"})
            self.assertIsNone(d["endpoint"], value)

    def test_region_defaults_to_auto_with_custom_endpoint(self):
        d = s3_env({"S3_ENDPOINT_URL": "https://s3.filebase.io"})
        self.assertEqual(d["region"], "auto")

    def test_region_defers_to_boto3_chain_without_endpoint(self):
        self.assertIsNone(s3_env({})["region"])

    def test_signature_version_defaults_to_s3v4(self):
        self.assertEqual(s3_env({})["signature_version"], "s3v4")

    def test_loaded_settings_hold_no_placeholder(self):
        self.assertNotIn("YOUR_R2_ENDPOINT", settings.S3_ENDPOINT_URL or "")
        self.assertNotIn("YOUR_R2_ENDPOINT", (settings.S3_BUCKET or "").upper())
