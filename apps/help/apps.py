"""Help app configuration."""

from django.apps import AppConfig


class HelpConfig(AppConfig):
    """Configuration for the help app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.help"
    verbose_name = "Help & Documentation"
