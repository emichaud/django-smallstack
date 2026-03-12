"""Heartbeat app configuration."""

from django.apps import AppConfig


class HeartbeatConfig(AppConfig):
    """Configuration for the heartbeat/uptime monitoring app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.heartbeat"
    verbose_name = "Heartbeat Monitoring"

    def ready(self):
        from apps.smallstack.navigation import nav

        nav.register(
            section="admin",
            label="Status",
            url_name="heartbeat:dashboard",
            icon_svg='<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M3.5 18.49l6-6.01 4 4L22 6.92l-1.41-1.41-7.09 7.97-4-4L2 16.99z"/></svg>',  # noqa: E501
            staff_required=True,
            order=20,
        )
