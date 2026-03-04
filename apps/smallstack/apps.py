"""SmallStack core app configuration."""

from django.apps import AppConfig


class SmallStackConfig(AppConfig):
    """Configuration for the SmallStack core app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.smallstack"
    verbose_name = "SmallStack"
