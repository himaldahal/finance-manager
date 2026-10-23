"""Create a demo user with a year of realistic data. For throwaway databases only."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app import demo, services


class Command(BaseCommand):
    help = "Seed a demo user with 12 months of data (refuses to run when DEBUG is off unless --force)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="demo-password-123")
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--force", action="store_true", help="run even when DEBUG is off")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError("seed_demo only runs with DEBUG=1 (or --force). It is meant for throwaway databases.")
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=opts["username"], defaults={"email": "demo@example.com", "first_name": "Demo", "last_name": "User"})
        if not created:
            raise CommandError(f"User {opts['username']!r} already exists.")
        user.set_password(opts["password"])
        user.save()
        demo.seed_user(user, seed=opts["seed"])
        count = user.transactions.count()
        self.stdout.write(self.style.SUCCESS(
            f"Created demo user {opts['username']!r} with {count} transactions. Balance: {services.balance_for(user)}"))
