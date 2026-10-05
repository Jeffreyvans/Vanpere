from django.test import TestCase, override_settings


class SecurityHeaderTests(TestCase):
    def test_csp_on_public_pages_not_admin(self):
        csp = self.client.get("/")["Content-Security-Policy"]
        for part in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'", "script-src 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("Content-Security-Policy", self.client.get("/admin/login/"))

    @override_settings(STORAGE_BACKEND="s3", S3_BUCKET="bkt", S3_ENDPOINT_URL="https://acc.r2.cloudflarestorage.com")
    def test_csp_allows_bucket_for_images_and_uploads(self):
        csp = self.client.get("/")["Content-Security-Policy"]
        for origin in ("https://acc.r2.cloudflarestorage.com", "https://bkt.acc.r2.cloudflarestorage.com"):
            self.assertEqual(csp.count(origin), 2, origin)  # img-src and connect-src

    def test_healthz_and_robots(self):
        self.assertEqual(self.client.get("/healthz/").content, b"ok")
        robots = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /event/", robots)
        self.assertIn("Disallow: /dashboard/", robots)
