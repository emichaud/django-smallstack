"""AppConfig for the notifications primitive."""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("smallstack.notifications")


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    # "notifications" is a common noun a downstream project may want for its
    # own app — namespace the label (house style: smallstack_runbook,
    # smallstack_datasets). Final before 0001_initial; changing it later is a
    # migration-history rename.
    label = "smallstack_notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_NOTIFICATIONS_ENABLED", True):
            return
        # No nav entry — the bell in the topbar is the entry point (it serves
        # every authenticated user, not just staff, so the admin drawer is the
        # wrong home). No signals to connect: producers call
        # notifications.notify() directly.
