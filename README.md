# VanPere Digital

Multi-event, mobile-first photo-sharing platform. The administrator creates an event (wedding, birthday, funeral, church event, corporate function, graduation) for a customer, shares the generated QR code or WhatsApp link, and guests upload and view photos with no account. There is no public registration: the single built-in administrator account is created at deploy time by `create_admin`.

Stack: Django 5 monolith (templates, vanilla-JS ES modules, no build step), PostgreSQL, S3-compatible object storage behind a swappable abstraction (with a local filesystem backend), Django REST Framework only for the upload and gallery JSON APIs, WhiteNoise, Gunicorn, Render.

## Local development (no cloud credentials needed)

    python3.12 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env            # defaults: SQLite, local storage, file-based email
    # then edit .env and set ADMIN_EMAIL / ADMIN_PASSWORD (never commit the password)
    python manage.py makemigrations accounts events photos
    python manage.py migrate
    python manage.py createcachetable
    python manage.py create_admin          # built-in administrator (ADMIN_EMAIL, ADMIN_PASSWORD)
    python manage.py seed_demo             # demo event and 8 sample photos
    python manage.py runserver

Then open http://localhost:8000. Sign in as the administrator, create an event for the customer, hand over the guest link, open it in a private window, upload photos, view the gallery and `/slideshow/`, and moderate in `/dashboard/`. `seed_demo` prints the demo guest link (it refuses to run when `DEBUG` is off unless you pass `--force`).

Quality checks: `python manage.py test`, `ruff check .`, and `DEBUG=False SECRET_KEY=<50+ random chars> ALLOWED_HOSTS=example.com python manage.py check --deploy`. Run tests with `DEBUG=True` in your environment.

**Commit the generated `migrations/` folders** (`accounts`, `events`, `photos`) before deploying: the Render build runs `migrate`, which needs them.

## Configuration

All settings come from the environment (see `.env.example`).

| Variable | Purpose |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | Core Django. `SITE_URL` builds absolute links (QR codes, emails, Open Graph). On Render the service hostname is added to the allowed hosts automatically. |
| `DATABASE_URL` | PostgreSQL URL; SQLite is used only when unset. |
| `TIME_ZONE` | Default `Africa/Harare`. Stored in UTC, shown in local time. |
| `STORAGE_BACKEND` | `local` or `s3`. `MEDIA_ROOT` for local. |
| `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_SIGNATURE_VERSION`, `AWS_S3_ADDRESSING_STYLE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Object storage (Filebase by default: `https://s3.filebase.io`, bucket `vanpere`, region `auto`, signature `s3v4`, path addressing). The legacy `S3_*` names are still accepted. The two keys must exist only in the server environment (Render dashboard); never commit, print or expose them. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | File-based backend locally (`EMAIL_FILE_PATH`, default `var/dev-emails`), SMTP in production. |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES` | Login and PIN lockout. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | The one built-in administrator. `create_admin` (run by `build.sh` after migrations) creates the account if missing, as staff/superuser, with the password stored only as a Django hash. It is idempotent, never prints the password, and only needs `ADMIN_PASSWORD` when the account does not exist yet. |
| `UPLOAD_RATE_PER_DEVICE`, `UPLOAD_RATE_PER_IP`, `REPORT_RATE_PER_DEVICE`, `REPORT_RATE_PER_IP` | Hourly request limits. |
| `REPORT_AUTO_HIDE_THRESHOLD` | Reports before a photo is hidden pending review (default 3). |
| `DEFAULT_EVENT_EXPIRY_DAYS` | Default expiry after the event date (90). |
| `EXPIRY_WARNING_DAYS`, `PURGE_GRACE_DAYS`, `ORPHAN_MAX_AGE_HOURS` | Expiry warnings (`7,1`), file purge grace (14), orphan age (24). |
| `ORGANISER_QUOTA_MB`, `ZIP_MAX_PHOTOS`, `ZIP_WARN_PHOTOS` | Soft storage quota (warning only), ZIP cap and warning. |
| `LOG_LEVEL` | Default `INFO`. |

## What each app does

- `config/`: settings, URLs, security-header (CSP) middleware, health check, robots.txt.
- `accounts/`: the single built-in administrator (`create_admin`), email login, signed expiring verification links, throttled login, password reset, branded HTML+text emails. There is no registration URL, form or API.
- `events/`: `Event` model, organiser pages, public guest page with Open Graph tags, sharing (WhatsApp first), QR PNG/SVG, A4/A5/table-card PDF posters, viewing PIN, expiry lifecycle (`expire_events`), `seed_demo`. `timeutils.py` is the single source of expiry maths.
- `photos/`: upload API (consent, duplicate check, presigned or fallback upload, finalise), image pipeline, gallery/viewer/slideshow pages and API, reports, guest delete, signed local media view, `cleanup_orphans`.
- `storage/`: `PhotoStorage` interface with `LocalPhotoStorage` and `S3PhotoStorage`; `get_storage()` reads `STORAGE_BACKEND`. No other module touches boto3 or the filesystem for photos.
- `dashboard/`: owner-scoped overview, moderation, quick review, reports queue, contributors, ZIP download, regenerate code, delete event.

## Privacy behaviour

- GPS and all other metadata are removed from every shared version: photos are validated by content, orientation-corrected, then re-encoded from raw pixels into original, medium and thumbnail JPEGs (tested). Re-encoding drops embedded colour profiles, so wide-gamut photos can look slightly less saturated. The browser also strips metadata when it resizes.
- IP addresses and device tokens are stored only as keyed hashes (HMAC with the server secret) and are not logged. Consent records a timestamp and IP hash.
- Event codes are random and unguessable; the UUID is never public. Gallery access respects PIN, expiry and approval at every JSON and file URL (the local media view re-checks on each request). Event pages are `noindex` and disallowed in `robots.txt`.
- Guests delete only their own uploads, identified by a device token compared in constant time.
- After expiry and a grace period, photos, consent records and files are deleted; only minimal event metadata remains.

## Uploads in brief

The browser resizes (2560 px, or 1600 px in low-bandwidth mode), computes SHA-256, skips photos already shared, then uploads straight to the bucket with a presigned **PUT** (works on Filebase, B2, S3 and Wasabi; presigned POST policies are not used). If the backend is `local`, presigning fails or CORS is missing, it falls back to a multipart POST to Django. The queue persists in IndexedDB and resumes after reloads and reconnects with exponential backoff. HEIC is converted on the server. The pipeline (`photos/services/image_pipeline.py`) is a pure function of a photo id; to move it to Celery/RQ, enqueue `process_photo(photo_id)` from the finalise endpoint instead of calling it.

## Photo links, pinch zoom and offline page (Stage 8)
- **Per-photo links:** the viewer's Share button shares `/event/<code>/p/<photo_id>/`, a page showing that photo with download and "view the whole gallery" buttons and its own share buttons. It follows the gallery rules (approved only, expiry, PIN; the organiser can open any of their own photos). WhatsApp previews use a stable `/event/<code>/p/<photo_id>/og.jpg`, available only for approved photos of open events without a PIN.
- **Zoom:** two-finger pinch (up to 5x), double-tap or double-click, trackpad pinch, `+`/`-`/`0` keys; drag or arrow keys pan when zoomed, and swipe navigation is paused while zoomed.
- **Service worker** (`/event/sw.js`, scope `/event/`): precaches the upload page's static files and keeps the last copy of each visited upload page for offline opening. It never caches `/api/`, `/media/`, galleries or other pages. Production static files now also rewrite JavaScript `import` paths to hashed names (`config/staticstorage.py`, Django 4.2+).

## Operations

- `python manage.py expire_events [--dry-run]`: marks expired events, emails organisers 7 and 1 days before expiry (`EXPIRY_WARNING_DAYS`; changing an event's expiry resets its warnings), and deletes files for events expired longer than `PURGE_GRACE_DAYS`. Idempotent and safe to re-run; logs a summary of counts only.
- `python manage.py cleanup_orphans [--hours N] [--dry-run]`: removes uploads never finalised after 24 hours.
- Both run daily as Render cron jobs in `render.yaml`. **Render cron schedules are UTC.** Africa/Harare is UTC+2 with no daylight saving, so `0 0 * * *` runs at 02:00 Harare (cleanup at `30 0 * * *`, 02:30).

## Deployment on Render (Filebase as the object store)

`render.yaml` is a hand-written blueprint that has **not** been validated against Render; if the dashboard rejects a field (plan names and environment-group options change), adjust it or enter the values in the dashboard.

1. **Bucket.** In Filebase, use the bucket `vanpere` (already configured in `render.yaml` as `AWS_STORAGE_BUCKET_NAME`). Keep it private - do **not** make it public to fix uploads.
2. **CORS** on the bucket (Filebase's S3 API, replace the origin with your `SITE_URL`):

        aws --endpoint-url https://s3.filebase.io s3api put-bucket-cors --bucket vanpere \
          --cors-configuration '{"CORSRules":[{"AllowedOrigins":["https://your-site.onrender.com"],
          "AllowedMethods":["PUT"],"AllowedHeaders":["Content-Type"],"MaxAgeSeconds":3600}]}'

3. **Access keys.** Filebase dashboard, API keys, create a key for this bucket; copy the access key and secret. They are server-side only: entered in Render as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, never committed, printed, logged or sent to the browser. The non-secret settings - endpoint `https://s3.filebase.io`, `AWS_S3_REGION_NAME=auto`, `AWS_STORAGE_BUCKET_NAME=vanpere`, `AWS_S3_SIGNATURE_VERSION=s3v4`, `AWS_S3_ADDRESSING_STYLE=path` - are already set in the `vanpere-shared` group of `render.yaml`.
4. **Database.** In Render create the production PostgreSQL instance (the blueprint does not create one) - it is the permanent production database. **Push** the repository (with the committed `migrations/` folders) to GitHub, then in Render choose New, Blueprint, and select it. Render creates the web service and two cron jobs; all three read the same database through `DATABASE_URL`.
5. **Set environment variables** marked "sync: false" on the web service **and on both cron jobs**: `DATABASE_URL` (the private database URL of the production PostgreSQL instance - entered in the Render Dashboard only; never commit it, never put it in `render.yaml`, never paste it into chat or Git), plus `SITE_URL` (e.g. `https://vanpere-digital.onrender.com`), `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, plus `ADMIN_EMAIL` and `ADMIN_PASSWORD` (the built-in administrator; store the password as a secret, never in Git), plus `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` if you use a custom domain. `SECRET_KEY` is generated (shorter generated keys are stretched to 50+ characters automatically). The crons need the same `DATABASE_URL`, Filebase keys and SMTP settings.
6. **First deploy** runs `build.sh` (install, `collectstatic`, `migrate`, `createcachetable`, `create_admin`). `create_admin` is idempotent: it creates the administrator only if the account does not exist and never prints the password. Check `/healthz/` returns `ok`.
7. **Sign in** at `/accounts/login/` with `ADMIN_EMAIL` and the `ADMIN_PASSWORD` you set. Password reset and email verification work for that account.
8. **Verify the cron jobs**: open each cron job, click "Trigger Run", and check the log for `expire_events: marked=... ` and `cleanup_orphans: removed=...`.

`pillow-heif` and ReportLab ship binary wheels for Python 3.12 on Linux, so no system packages should be needed; this has not been verified on Render. Gunicorn runs threaded workers with a 120-second timeout so ZIP downloads can stream.

## Posters

A4 and A5 use ReportLab page sizes. The table card is 100 x 150 mm trim size with **no bleed**; the ivory background has at least 9 mm margins, so a printer can extend it by 3 mm of bleed.

## Known limitations

- Not run in the build environment: `check --deploy` with production values, and the Render blueprint (see above). The Django test suite and `python manage.py check` pass locally (104 tests); run them before launch.
- The service worker only caches the upload page and static files so the page opens on a poor connection. It does not upload in the background: queued uploads resume when the upload page is open and online.
- Pinch zoom scales about the image centre, not the pinch point. Photo links work for anyone who has them (the photo is approved, the event is open and any PIN is entered), and link-preview images only work for events without a PIN.
- Image URLs are signed for one hour: a gallery tab left open longer needs a reload (the slideshow refreshes URLs every poll). With S3 storage, file URLs cannot re-check PIN or approval at fetch time.
- Presigned PUT URLs cannot cap upload size at the bucket; the size limit is enforced when the upload is finalised, and unfinalised objects are removed by `cleanup_orphans`.
- The server-fallback upload reads the file into memory (capped by the event size limit, at most 50 MB).
- The cover endpoint is public even when a viewing PIN is set (link previews need it). Covers accept JPG, PNG and WEBP only.
- ZIP downloads are limited by photo count (`ZIP_MAX_PHOTOS`), not bytes. The pre-expiry email is sent by the cron job, so its timing is daily.
- Throttling uses the database cache and the first `X-Forwarded-For` entry, which a client can forge; the per-email login limit is the stronger control.
- The default Open Graph image is plain (name and tagline on a dark background); the Privacy and Terms pages are placeholders that need legal review.
