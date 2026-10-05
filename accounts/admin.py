from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "email_verified", "is_staff")
    list_filter = ("email_verified", "is_staff")
    search_fields = ("email", "full_name")
