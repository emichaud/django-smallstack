from django.apps import AppConfig


class ShowcaseConfig(AppConfig):
    """SmallStack's demo pages. Delete the app to drop them (see views.py)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.showcase"
    verbose_name = "Showcase"
