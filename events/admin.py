from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "public_code", "owner", "event_type", "event_date", "expires_at", "is_active")
    list_filter = ("event_type", "is_active", "moderation_enabled", "allow_uploads")
    search_fields = ("name", "public_code", "owner__email")
    readonly_fields = ("id", "public_code", "cover_image", "view_pin_hash", "created_at", "storage_used_bytes",
                       "expiry_marked_at", "files_purged_at", "warned_thresholds")
