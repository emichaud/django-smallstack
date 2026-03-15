"""
Management command to generate Playwright auth state for shot-scraper.

Creates a Django session for the dev superuser and outputs it in
Playwright's storage state format (JSON). Use with shot-scraper's
--auth flag to screenshot authenticated pages.

Usage:
    uv run python manage.py screenshot_auth > /tmp/shot-auth.json
    shot-scraper http://localhost:8005/backups/ --auth /tmp/shot-auth.json -o backups.png

WARNING: This command is for DEVELOPMENT ONLY.
"""

import json

from decouple import config
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand

User = get_user_model()

SESSION_ENGINE = "django.contrib.sessions.backends.db"


class Command(BaseCommand):
    help = "Generate Playwright auth state (JSON) for shot-scraper"

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            default="localhost",
            help="Cookie domain (default: localhost)",
        )

    def handle(self, *args, **options):
        username = config("DEV_SUPERUSER_USERNAME", default="admin")
        password = config("DEV_SUPERUSER_PASSWORD", default="admin")

        # Get or create the dev superuser
        user = User.objects.filter(username=username).first()
        if not user:
            user = User.objects.create_superuser(username=username, password=password)
            self.stderr.write(self.style.WARNING(f"Created dev superuser: {username}"))

        # Create a session programmatically
        session = SessionStore()
        session["_auth_user_id"] = str(user.pk)
        session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        session["_auth_user_hash"] = user.get_session_auth_hash()
        session.create()

        domain = options["domain"]
        cookie_name = settings.SESSION_COOKIE_NAME

        # Output Playwright storage state format
        storage_state = {
            "cookies": [
                {
                    "name": cookie_name,
                    "value": session.session_key,
                    "domain": domain,
                    "path": "/",
                    "httpOnly": True,
                    "secure": False,
                    "sameSite": "Lax",
                }
            ],
            "origins": [],
        }

        self.stdout.write(json.dumps(storage_state, indent=2))
