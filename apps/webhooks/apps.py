"""Webhooks app configuration.

``ready()`` wires the outbound event source (the global save/delete signals),
autodiscovers inbound handlers (each app's ``webhook_handlers.py``), and registers
the nav / dashboard / status surfaces. Everything is best-effort — a registration
failure must never take down startup — and no DB access happens in ``ready()``.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class WebhooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.webhooks"
    verbose_name = "Webhooks"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_WEBHOOKS_ENABLED", True):
            return

        # Outbound event source: the global post_save/post_delete observer.
        if getattr(settings, "SMALLSTACK_WEBHOOKS_OUTBOUND", True):
            try:
                from . import signals  # noqa: F401 — importing registers the receivers
            except Exception:  # noqa: BLE001
                logger.warning("webhooks: signal registration failed", exc_info=True)

        # Ensure the four built-in default seams are registered even if the module
        # wasn't imported yet (defensive — hooks.py registers them at import).
        try:
            from . import hooks

            hooks.register_default_hooks()
        except Exception:  # noqa: BLE001
            logger.warning("webhooks: default hook registration failed", exc_info=True)

        # Autodiscover extension seams + inbound handlers from each app's webhook_*.py
        # (pure imports, no DB) — the same pattern as mcp_tools.py / webhook_handlers.py.
        seam_modules = (
            "webhook_transforms",  # @webhook_transform
            "webhook_auths",  # @webhook_auth
            "webhook_verifiers",  # @webhook_verifier
            "webhook_challenges",  # @webhook_challenge
        )
        try:
            from apps.smallstack.autodiscover import autodiscover_app_modules

            autodiscover_app_modules(seam_modules, skip_label=self.label)
        except Exception:  # noqa: BLE001
            logger.warning("webhooks: seam autodiscovery failed", exc_info=True)

        # Inbound: import every app's webhook_handlers.py so @webhook_handler
        # decorators register (pure imports, no DB).
        if getattr(settings, "SMALLSTACK_WEBHOOKS_INBOUND", True):
            try:
                from apps.smallstack.autodiscover import autodiscover_app_modules

                autodiscover_app_modules(("webhook_handlers",), skip_label=self.label)
            except Exception:  # noqa: BLE001
                logger.warning("webhooks: handler autodiscovery failed", exc_info=True)

        self._register_surfaces()

    def _register_surfaces(self) -> None:
        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="Webhooks",
                url_name="webhooks_dashboard",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" '
                    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                    'stroke-linejoin="round"><path d="M18 16.98h-5.99c-1.66 0-3.01-1.34-'
                    '3.01-3s1.35-3 3.01-3H18"/><path d="M8 8.01a3 3 0 1 0 0 6"/>'
                    '<path d="M12 12h.01"/></svg>'
                ),
                staff_required=True,
                order=26,
                active_prefix="/smallstack/webhooks/",
            )
        except Exception:  # noqa: BLE001
            logger.warning("webhooks: nav registration failed", exc_info=True)

        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import WebhooksDashboardWidget

            dashboard.register(WebhooksDashboardWidget())
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("webhooks: dashboard widget registration failed", exc_info=True)

        try:
            from apps.smallstack import monitors

            from .monitors import WebhooksMonitor, WebhooksService

            monitors.register_service(WebhooksService())
            monitors.register_monitor(WebhooksMonitor())
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("webhooks: status monitor registration failed", exc_info=True)
