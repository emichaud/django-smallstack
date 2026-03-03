"""Admin theme app configuration."""

from django.apps import AppConfig


class AdminThemeConfig(AppConfig):
    """Configuration for the admin theme app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_theme"
    verbose_name = "Admin Theme"
