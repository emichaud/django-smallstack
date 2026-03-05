"""Activity app configuration."""

from django.apps import AppConfig


class ActivityConfig(AppConfig):
    """Configuration for the activity tracking app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.activity"
    verbose_name = "Activity Tracking"
