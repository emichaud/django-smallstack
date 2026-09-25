"""Background tasks — the daily retention prune.

Dogfoods the scheduler primitive: the prune is a plain @task, promoted to a
recurring job by @scheduled when the scheduler app is present. Notifications
never *depends* on the worker — the table just grows until pruned.
"""

from __future__ import annotations

from django.conf import settings
from django.tasks import task

from . import services


@task()
def prune_notifications() -> int:
    """Delete notifications past SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS."""
    return services.prune()


try:
    from apps.scheduler import scheduled

    if getattr(settings, "SMALLSTACK_NOTIFICATIONS_ENABLED", True):
        prune_notifications = scheduled(
            every="1d", name="Notifications: prune old rows"
        )(prune_notifications)
except ImportError:  # scheduler app not installed — prune stays manual
    pass
