from django.core.management.base import BaseCommand

from app import services


class Command(BaseCommand):
    help = "Create every due recurring transaction (safe to run repeatedly, e.g. daily from cron)."

    def handle(self, *args, **options):
        created = services.apply_due()
        purged = services.purge_deleted()
        self.stdout.write(f"Created {created} transaction(s); removed {purged} deleted transaction(s) past the undo window.")
