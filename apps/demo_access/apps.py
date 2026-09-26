"""AppConfig for the elevated-access scenario (Scenario C — REST + webhooks)."""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.demo_access")


class DemoAccessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo_access"
    label = "demo_access"
    verbose_name = "Demo · Elevated access"

    def ready(self) -> None:
        try:
            from . import signals  # noqa: F401 — connects on import
        except Exception:  # noqa: BLE001
            logger.warning("demo_access: signal wiring failed", exc_info=True)

        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="Access requests",
                url_name="demo/access/requests-list",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 '
                    "2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 "
                    "1.34-3 3-3s3 1.34 3 3v2H9V6zm3 12c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 "
                    '2-.9 2-2 2z"/></svg>'
                ),
                staff_required=True,
                active_prefix="/demo/access/",
            )
        except Exception:  # noqa: BLE001
            logger.warning("demo_access: nav registration failed", exc_info=True)
