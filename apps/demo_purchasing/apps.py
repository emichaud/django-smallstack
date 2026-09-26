"""AppConfig for the purchasing approval scenario (Scenario A — web)."""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.demo_purchasing")


class DemoPurchasingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo_purchasing"
    label = "demo_purchasing"
    verbose_name = "Demo · Purchasing"

    def ready(self) -> None:
        # Signals live in signals.py and are connected by importing it here
        # (house convention). This app only *observes* approvals — every write
        # to PurchaseRequest happens in the @approval_kind callback.
        try:
            from . import signals  # noqa: F401 — connects on import
        except Exception:  # noqa: BLE001 — a receiver must not break startup
            logger.warning("demo_purchasing: signal wiring failed", exc_info=True)

        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="Purchase requests",
                url_name="demo/purchasing/requests-list",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M7 18c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zM1 2v2h2l3.6 '
                    "7.59-1.35 2.45c-.16.28-.25.61-.25.96 0 1.1.9 2 2 2h12v-2H7.42c-.14 "
                    "0-.25-.11-.25-.25l.03-.12L8.1 13h7.45c.75 0 1.41-.41 "
                    "1.75-1.03l3.58-6.49A1 1 0 0 0 20 4H5.21l-.94-2H1zm16 16c-1.1 0-2 "
                    '.9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>'
                ),
                staff_required=True,
                active_prefix="/demo/purchasing/",
            )
        except Exception:  # noqa: BLE001
            logger.warning("demo_purchasing: nav registration failed", exc_info=True)
