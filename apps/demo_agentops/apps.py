"""AppConfig for the agent-action approval scenario (Scenario B — MCP / AI)."""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.demo_agentops")


class DemoAgentOpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo_agentops"
    label = "demo_agentops"
    verbose_name = "Demo · Agent ops"

    def ready(self) -> None:
        try:
            from . import signals  # noqa: F401 — connects on import
        except Exception:  # noqa: BLE001
            logger.warning("demo_agentops: signal wiring failed", exc_info=True)

        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="Agent actions",
                url_name="demo/agentops/actions-list",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M20 9V7a2 2 0 0 0-2-2h-3V3h-2v2h-2V3H9v2H6a2 2 0 0 0-2 '
                    "2v2H2v2h2v2H2v2h2v2a2 2 0 0 0 2 2h3v2h2v-2h2v2h2v-2h3a2 2 0 0 0 "
                    "2-2v-2h2v-2h-2v-2h2V9h-2zm-2 8H6V7h12v10zM9 10h2v4H9zm4 0h2v4h-2z"
                    '"/></svg>'
                ),
                staff_required=True,
                active_prefix="/demo/agentops/",
            )
        except Exception:  # noqa: BLE001
            logger.warning("demo_agentops: nav registration failed", exc_info=True)
