from django.contrib import admin

from .models import Photo, UploadConsent


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "event", "status", "uploader_name", "width", "height", "created_at")
    list_filter = ("status",)
    search_fields = ("event__name", "event__public_code", "uploader_name")
    readonly_fields = ("id", "event", "uploader_hash", "ip_hash", "content_hash", "batch_id",
                       "original_bytes", "medium_bytes", "thumb_bytes", "created_at", "finalised_at")


@admin.register(UploadConsent)
class UploadConsentAdmin(admin.ModelAdmin):
    list_display = ("event", "accepted_at")
    readonly_fields = ("event", "device_hash", "ip_hash", "accepted_at")


from .models import Report  # noqa: E402


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("photo", "reason", "dismissed", "created_at")
    list_filter = ("reason", "dismissed")
    readonly_fields = ("photo", "reporter_hash", "created_at")
