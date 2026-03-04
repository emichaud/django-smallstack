"""
Management command to create a development superuser.

WARNING: This command is for DEVELOPMENT ONLY.
Do NOT use in production environments.
"""

from decouple import config
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Create a development superuser (DEVELOPMENT ONLY)"

    def handle(self, *args, **options):
        username = config("DEV_SUPERUSER_USERNAME", default="admin")
        password = config("DEV_SUPERUSER_PASSWORD", default="admin")

        self.stdout.write(
            self.style.WARNING(
                "\n" + "=" * 60 + "\n"
                "WARNING: This command is for DEVELOPMENT ONLY.\n"
                "Do NOT use in production environments.\n"
                "=" * 60 + "\n"
            )
        )

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f"User '{username}' already exists. Skipping creation."))
            return

        User.objects.create_superuser(
            username=username,
            password=password,
        )

        self.stdout.write(self.style.SUCCESS(f"Successfully created development superuser: {username}"))
