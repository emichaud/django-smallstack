"""
Management command to create a development superuser.

WARNING: This command is for DEVELOPMENT ONLY.
Do NOT use in production environments.
"""

from decouple import config
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = "Create a development superuser (DEVELOPMENT ONLY)"

    def handle(self, *args, **options):
        # Hard guard, not just a printed warning: this mints a well-known
        # admin/admin superuser. Refuse outside DEBUG so `make setup` against a
        # production DB can't create a backdoor. Use `ensure_superuser`
        # (env-driven, idempotent) in production. (Audit L3.)
        if not settings.DEBUG:
            raise CommandError(
                "create_dev_superuser refuses to run with DEBUG=False. "
                "Use `ensure_superuser` (env-driven) for production superusers."
            )

        username = config("DEV_SUPERUSER_USERNAME", default="admin")
        password = config("DEV_SUPERUSER_PASSWORD", default="admin")

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("WARNING: This command is for DEVELOPMENT ONLY."))
        self.stdout.write(self.style.WARNING("Do NOT use in production environments."))
        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write("")

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"User '{username}' already exists. Skipping creation."))
            return

        User.objects.create_superuser(
            username=username,
            password=password,
        )

        self.stdout.write(self.style.SUCCESS(f"Successfully created development superuser: {username}"))
        self.stdout.write(f"  Username: {username}")
        self.stdout.write(f"  Password: {password}")
