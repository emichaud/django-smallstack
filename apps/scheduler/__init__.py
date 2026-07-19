"""SmallStack scheduler — DB-backed recurring jobs over django.tasks."""

from .decorators import scheduled

__all__ = ["scheduled"]

default_app_config = "apps.scheduler.apps.SchedulerConfig"
