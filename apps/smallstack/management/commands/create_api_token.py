"""Management command to create API tokens for REST API authentication."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.smallstack.models import APIToken

User = get_user_model()


class Command(BaseCommand):
    help = "Create an API token for a user"

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username to create the token for")
        parser.add_argument("--name", default="CLI Token", help="Token name/label")
        parser.add_argument(
            "--access-level",
            choices=["auth", "staff", "readonly"],
            default="staff",
            help="Token access level (default: staff)",
        )

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"User '{options['username']}' does not exist")

        token, raw_key = APIToken.create_token(
            user=user, name=options["name"], access_level=options["access_level"],
        )
        self.stdout.write(self.style.SUCCESS(f"Token created for {user.username}:"))
        self.stdout.write(f"  Access level: {token.access_level}")
        self.stdout.write(f"\n  {raw_key}\n")
        self.stdout.write(self.style.WARNING("Save this key — it cannot be retrieved later."))
