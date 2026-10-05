from django.core.management.base import BaseCommand

from photos.services.cleanup import cleanup_orphans


class Command(BaseCommand):
    help = "Remove uploads that were never finalised (older than ORPHAN_MAX_AGE_HOURS)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=None, help="Override the age threshold.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        s = cleanup_orphans(max_age_hours=options["hours"], dry_run=options["dry_run"])
        self.stdout.write(f"cleanup_orphans: removed={s['removed']}" + (" (dry run)" if options["dry_run"] else ""))
