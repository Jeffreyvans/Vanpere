"""VanPere Digital settings (environment-driven)."""
import hashlib
import os
import sys
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

from .s3env import s3_env

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"


def env_bool(k, d=False):
    return os.getenv(k, str(d)).lower() in ("1", "true", "yes")


DEBUG = env_bool("DEBUG", True)
SECRET_KEY = os.getenv("SECRET_KEY") or ("dev-only-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is required when DEBUG is off")
if not DEBUG and len(SECRET_KEY) < 50:  # e.g. Render's generated value; keeps `check --deploy` clean
    SECRET_KEY = hashlib.sha512(SECRET_KEY.encode()).hexdigest()
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000")
SITE_NAME = "VanPere Digital"

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework",
    "accounts", "events", "photos", "storage", "dashboard",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.CSPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "config.context_processors.site",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

_db = os.getenv("DATABASE_URL")
DATABASES = {"default": dj_database_url.parse(_db, conn_max_age=600) if _db
             else {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation." + n}
    for n in ("UserAttributeSimilarityValidator", "MinimumLengthValidator",
              "CommonPasswordValidator", "NumericPasswordValidator")
]

LANGUAGE_CODE = "en"
TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Harare")
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG or TESTING else "config.staticstorage.ManifestStorage"
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Object storage (Filebase by default: endpoint https://s3.filebase.io, bucket vanpere,
# region auto, signature s3v4). AWS_* names win, legacy S3_* names still work and
# template placeholders are treated as unset (see config/s3env.py).
STORAGE_BACKEND = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()
MEDIA_ROOT = BASE_DIR / os.getenv("MEDIA_ROOT", "media")
_s3 = s3_env(os.environ)
S3_ENDPOINT_URL = _s3["endpoint"]
S3_REGION = _s3["region"]
S3_BUCKET = _s3["bucket"]
S3_ACCESS_KEY_ID = _s3["access_key_id"]
S3_SECRET_ACCESS_KEY = _s3["secret_access_key"]
S3_ADDRESSING_STYLE = _s3["addressing_style"]
S3_SIGNATURE_VERSION = _s3["signature_version"]

# Console backend flushes sys.stdout and raises OSError [Errno 22] on Windows.
_default_email_backend = (
    "django.core.mail.backends.filebased.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND") or _default_email_backend
EMAIL_FILE_PATH = Path(os.getenv("EMAIL_FILE_PATH") or (BASE_DIR / "var" / "dev-emails"))
if EMAIL_BACKEND == "django.core.mail.backends.filebased.EmailBackend":
    EMAIL_FILE_PATH.mkdir(parents=True, exist_ok=True)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "VanPere Digital <no-reply@example.com>")

LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_MINUTES = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15"))
REPORT_AUTO_HIDE_THRESHOLD = int(os.getenv("REPORT_AUTO_HIDE_THRESHOLD", "3"))
DEFAULT_EVENT_EXPIRY_DAYS = int(os.getenv("DEFAULT_EVENT_EXPIRY_DAYS", "90"))

X_FRAME_OPTIONS = "DENY"
LOGIN_URL = "/accounts/login/"
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Stage 2: accounts, throttling cache, verification
CACHES = {"default": {
    "BACKEND": "django.core.cache.backends.locmem.LocMemCache" if TESTING
    else "django.core.cache.backends.db.DatabaseCache",
    "LOCATION": "vanpere_cache",
}}
LOGIN_REDIRECT_URL = "accounts:home"
LOGOUT_REDIRECT_URL = "landing"
EMAIL_VERIFY_MAX_AGE = 3 * 24 * 3600  # seconds
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL") or "").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or ""

# Stage 4: uploads
UPLOAD_RATE_PER_DEVICE = int(os.getenv("UPLOAD_RATE_PER_DEVICE", "120"))  # per hour
UPLOAD_RATE_PER_IP = int(os.getenv("UPLOAD_RATE_PER_IP", "400"))  # per hour
REST_FRAMEWORK = {"DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]}

# Stage 5: reporting limits (per hour)
REPORT_RATE_PER_DEVICE = int(os.getenv("REPORT_RATE_PER_DEVICE", "20"))
REPORT_RATE_PER_IP = int(os.getenv("REPORT_RATE_PER_IP", "100"))

# Stage 6: dashboard limits
ORGANISER_QUOTA_MB = int(os.getenv("ORGANISER_QUOTA_MB", "2048"))  # soft quota, warning only
ZIP_MAX_PHOTOS = int(os.getenv("ZIP_MAX_PHOTOS", "2000"))
ZIP_WARN_PHOTOS = int(os.getenv("ZIP_WARN_PHOTOS", "500"))

# Stage 7: operations
EXPIRY_WARNING_DAYS = [int(x) for x in os.getenv("EXPIRY_WARNING_DAYS", "7,1").split(",") if x.strip()]
PURGE_GRACE_DAYS = int(os.getenv("PURGE_GRACE_DAYS", "14"))
ORPHAN_MAX_AGE_HOURS = int(os.getenv("ORPHAN_MAX_AGE_HOURS", "24"))
LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
