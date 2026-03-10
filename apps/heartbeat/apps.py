"""Heartbeat app configuration."""

from django.apps import AppConfig


class HeartbeatConfig(AppConfig):
    """Configuration for the heartbeat/uptime monitoring app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.heartbeat"
    verbose_name = "Heartbeat Monitoring"
