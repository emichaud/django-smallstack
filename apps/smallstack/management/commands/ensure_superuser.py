"""
Management command to ensure a superuser exists from environment variables.

Used by docker-entrypoint.sh to safely create the initial superuser
without shell-interpolating credentials into Python code.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Create a superuser from DJANGO_SUPERUSER_* environment variables (if not exists)"

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME/PASSWORD not set. Skipping.")
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Superuser '{username}' already exists.")
            return

        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@example.com")

        User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
        )
        self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created."))
