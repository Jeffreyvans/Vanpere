from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create the built-in administrator from ADMIN_EMAIL and ADMIN_PASSWORD. Idempotent."

    def handle(self, *args, **options):
        email = (getattr(settings, "ADMIN_EMAIL", "") or "").strip().lower()
        if not email:
            raise CommandError("Set ADMIN_EMAIL in the environment.")
        user = User.objects.filter(email=email).first()
        if user is not None:
            fields = []
            if not user.is_staff:
                user.is_staff = True
                fields.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                fields.append("is_superuser")
            if not user.email_verified:
                user.email_verified = True
                fields.append("email_verified")
            if fields:
                user.save(update_fields=fields)
            self.stdout.write("Administrator already exists.")
            return
        password = getattr(settings, "ADMIN_PASSWORD", "") or ""
        if not password:
            raise CommandError("Set ADMIN_PASSWORD in the environment to create the administrator.")
        User.objects.create_superuser(email, password, full_name="Administrator")
        self.stdout.write("Administrator account created.")
