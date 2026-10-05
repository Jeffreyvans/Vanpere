from django.core.management.base import BaseCommand

from events.expiry import run_expiry


class Command(BaseCommand):
    help = "Mark expired events, send expiry warnings, purge files after the grace period (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report what would happen, change nothing.")

    def handle(self, *args, **options):
        s = run_expiry(dry_run=options["dry_run"])
        self.stdout.write(f"expire_events: marked={s['marked']} warned={s['warned']} "
                          f"purged={s['purged']} email_failures={s['email_failures']}"
                          + (" (dry run)" if options["dry_run"] else ""))
