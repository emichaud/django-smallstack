"""Activity app configuration."""

from django.apps import AppConfig


class ActivityConfig(AppConfig):
    """Configuration for the activity tracking app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.activity"
    verbose_name = "Activity Tracking"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",
            label="Activity",
            url_name="activity:dashboard",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M5 9.2h3V19H5zM10.6 5h2.8v14h-2.8zm5.6 8H19v6h-2.8z"/></svg>',  # noqa: E501
            staff_required=True,
            order=10,
        )
