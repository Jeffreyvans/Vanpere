# VanPere Digital: requirement checklist

Status: **Done** = implemented and covered by a written test or reviewed code path; **Partial** = implemented with a stated limitation; **Deferred** = not built. `python manage.py test` (104 tests) and `python manage.py check` were executed and pass; `check --deploy` and the Render blueprint were not executed against production values.

| # | Requirement | Where | Status |
|---|---|---|---|
| 1 | Brand name capitalised everywhere (wordmark, titles, meta, nav, footer, emails, posters, legal pages, admin titles, metadata, render.yaml names, README) | `templates/base.html`, `templates/emails/`, `config/urls.py`, `pyproject.toml`, `render.yaml`, `events/qr.py` | Done |
| 1 | Text wordmark, SVG favicon, 1200x630 PNG Open Graph image | `templates/base.html`, `static/img/favicon.svg`, `static/img/og-default.png` | Done (OG image is plain) |
| 1 | Palette, serif/sans stacks, no external fonts, responsive, accessible (focus, labels, aria-live, reduced motion) | `static/css/main.css`, templates | Done |
| 2 | Django monolith, templates, vanilla JS modules, PostgreSQL via `DATABASE_URL`, SQLite fallback | `config/settings.py`, `static/js/` | Done |
| 2 | DRF only for presign/finalise/hash/gallery/delete | `photos/api.py`, `photos/gallery_api.py` | Done |
| 2 | Storage abstraction, local + S3, `STORAGE_BACKEND`, no binaries in DB | `storage/` | Done |
| 2 | Render, gunicorn, whitenoise, cron, `render.yaml` | `render.yaml`, `build.sh`, `config/settings.py` | Partial (blueprint not validated on Render) |
| 2 | Africa/Harare, `USE_TZ`, one expiry helper | `events/timeutils.py` | Done |
| 2 | Pinned versions, suggested libraries | `requirements.txt` | Done |
| 3 | Project layout, custom user from first migration | repository root, `accounts/models.py` | Done |
| 4 | Login, logout, verification (signed, expiring, resend), password reset | `accounts/` | Done |
| 4 | No public registration (no URL, form, link or API); one built-in administrator from `ADMIN_EMAIL`/`ADMIN_PASSWORD` via idempotent `create_admin`, hashed password only | `accounts/management/commands/create_admin.py`, `accounts/urls.py`, `build.sh`, `.env.example` | Done |
| 4 | Throttled login per IP and email, configurable | `accounts/throttle.py`, `accounts/forms.py` | Done |
| 4 | Branded emails (verification, reset, event-created, expiry warning), HTML + text | `templates/emails/`, `accounts/emails.py`, `events/emails.py` | Done |
| 5 | Event model and fields, 8-char unambiguous public code, UUID never public | `events/models.py` | Done |
| 5 | Create/edit form with defaults and exact expiry hint | `events/forms.py`, `static/js/event-form.js` | Done |
| 5 | Optional hashed viewing PIN, rate-limited, session memory | `events/pin.py`, `events/views.py` | Done |
| 5 | Expired state, organiser keeps dashboard until purge | `templates/events/public.html`, `events/expiry.py` | Done |
| 5 | Share buttons (WhatsApp primary, Facebook, email, copy, Web Share), Open Graph/Twitter tags | `templates/events/_share.html`, `static/js/share.js`, `templates/events/public.html` | Done |
| 6 | QR PNG (print quality, level H) and SVG, owner-only | `events/qr.py`, `events/views.py` | Done |
| 6 | A4, A5, table-card PDF posters, bleed noted | `events/qr.py`, README | Done |
| 7 | Guest event page: cover, details, photo count, name field, two buttons | `templates/events/public.html`, `templates/photos/upload.html` | Done |
| 7 | Consent notice recorded (timestamp, IP hash); device token for own-delete | `photos/api.py`, `static/js/upload/device.js` | Done |
| 8 | Multi-select, camera, drag and drop, previews, remove, progress, retry | `static/js/upload/uploader.js`, `templates/photos/upload.html` | Done |
| 8 | Client resize/compress, EXIF orientation, HEIC fallback | `static/js/upload/compress.js` | Done |
| 8 | SHA-256 duplicate check and server uniqueness | `static/js/upload/hash.js`, `photos/models.py`, `photos/api.py` | Done |
| 8 | Direct-to-storage presigned upload + server fallback, CORS documented | `storage/s3.py`, `photos/api.py`, README | Done (PUT, not POST) |
| 8 | IndexedDB resumable queue, backoff, low-bandwidth mode, concurrency 2/1, server throttles | `static/js/upload/queue.js`, `uploader.js`, `photos/ratelimit.py` | Done |
| 8 | Service worker (minimal, scoped) | `templates/sw.js`, `photos/views.py` (`service_worker`), `static/js/upload/uploader.js` | Done (offline page shell only) |
| 9 | Pipeline: validate, HEIC, orientation, strip GPS (tested), 3 versions, sizes, hash, storage counter, originals gated | `photos/services/` | Done |
| 9 | Signed time-limited URLs (S3) / signed Django view (local) | `storage/`, `photos/views.py` (`media`) | Done |
| 10 | Masonry gallery, lazy load, skeletons, stable ratios, infinite scroll + Load more | `static/js/gallery/gallery.js`, `templates/photos/gallery.html` | Done |
| 10 | Approved-only for guests | `photos/gallery_api.py` | Done |
| 10 | Viewer: swipe, keys, preload, zoom, share, download, report, own-delete | `static/js/gallery/viewer.js`, `photos/views.py` (`photo_page`, `photo_og`) | Done (pinch, double-tap, per-photo links) |
| 10 | Live slideshow: crossfade, polling, QR overlay, idle hide, wake lock, PIN-aware | `static/js/gallery/slideshow.js`, `templates/photos/slideshow.html` | Done |
| 11 | Overview cards (photos, contributors, storage, days remaining, pending, reports) | `dashboard/views.py`, `templates/dashboard/` | Done |
| 11 | Moderation tabs, bulk actions, reasons, cover, quick review | `dashboard/` | Done |
| 11 | Reports queue and auto-hide at threshold | `dashboard/views.py`, `photos/gallery_api.py` | Done |
| 11 | Contributors, remove all from a device | `dashboard/views.py` | Done |
| 11 | Streamed ZIP with cap/warning | `dashboard/services.py` | Done |
| 11 | Storage/usage per event and soft per-organiser quota | `dashboard/views.py`, `templates/dashboard/overview.html` | Done |
| 11 | Confirmed regenerate code, delete event, owner scoping (tested), admin title and filters | `dashboard/`, `*/admin.py`, `config/urls.py` | Done |
| 11 | Warning email before expiry when expiry changes | `events/expiry.py`, `events/forms.py` | Done (sent by cron, resets on change) |
| 12 | Landing page, FAQ, no fake testimonials | `templates/landing.html` | Done |
| 12 | Privacy/Terms placeholders, branded 404/403/500, robots.txt, noindex | `templates/legal/`, `templates/404.html` etc., `config/urls.py` | Done |
| 13 | Storage interface, factory, key safety, presign restrictions, finalise re-validates | `storage/`, `photos/api.py` | Partial (PUT URLs cannot cap size; enforced at finalise) |
| 14 | CSRF, secure cookies, HSTS, X-Frame-Options, CSP with bucket origins | `config/settings.py`, `config/middleware.py` | Done |
| 14 | Rate limits (login, PIN, upload, report, hash check), constant-time delete auth, no raw IP/token storage or logs | `accounts/`, `events/pin.py`, `photos/` | Done |
| 15 | `.env.example` with all variables | `.env.example` | Done |
| 16 | Local dev steps, `seed_demo` | README, `events/management/commands/seed_demo.py` | Done |
| 17 | `expire_events` (mark, warn, purge; idempotent), `cleanup_orphans`, Render crons (UTC conversion documented) | `events/expiry.py`, `photos/services/cleanup.py`, `render.yaml`, README | Done |
| 18 | `render.yaml`, `build.sh`, whitenoise, `/healthz/`, gunicorn, README deploy section | root files, README | Partial (not validated on Render) |
| 19 | Tests across all listed areas | `*/tests*.py` | Done (`python manage.py test`: 104 tests pass) |
| 19 | `check --deploy` clean | `config/settings.py` | Not run |
| 19 | Indexes, N+1 avoidance, pagination, ruff config | `photos/models.py`, `dashboard/views.py`, `pyproject.toml` | Done |

## Deferred or not verified
- Stage 8 built the three originally deferred items (pinch zoom, service worker, per-photo links); their JavaScript is syntax-checked only, not tried in a browser.
- Executed here: `python manage.py test` (104 tests, all pass) and `python manage.py check` (no issues). Not executed: `check --deploy` with production values, the Render blueprint, browser behaviour of the JavaScript (syntax-checked only).
- Needs your input: legal text for Privacy/Terms, production email provider, final Open Graph artwork.
