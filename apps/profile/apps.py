"""Profile app configuration."""

from django.apps import AppConfig


class ProfileConfig(AppConfig):
    """Configuration for the profile app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.profile"
    verbose_name = "User Profiles"

    def ready(self):
        # Import signals to register them
        from . import signals  # noqa: F401
