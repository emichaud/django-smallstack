"""AppConfig for the approvals primitive."""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("smallstack.approvals")


class ApprovalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.approvals"
    # Common-noun label, namespaced per house style (smallstack_runbook,
    # smallstack_datasets, smallstack_notifications). Final before 0001.
    label = "smallstack_approvals"
    verbose_name = "Approvals"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_APPROVALS_ENABLED", True):
            return

        # 1. Autodiscover kind declarations: every app's approvals.py module.
        try:
            from apps.smallstack.autodiscover import autodiscover_app_modules

            autodiscover_app_modules(("approvals",), skip_label=self.label)
        except Exception:  # noqa: BLE001
            logger.warning("approvals: kind autodiscovery failed", exc_info=True)

        # 2. Notification/email receivers for request + decision events.
        try:
            from . import receivers  # noqa: F401 — connects on import
        except Exception:  # noqa: BLE001
            logger.warning("approvals: receiver wiring failed", exc_info=True)

        self._register_surfaces()

    def _register_surfaces(self) -> None:
        """Nav + dashboard registrations — each isolated so one failure can't
        block startup (scheduler exemplar)."""
        try:
            from apps.smallstack.navigation import nav

            icon = (
                '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z'
                'm-2 16-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
            )
            nav.register(
                section="admin",
                label="Approvals",
                url_name="approvals/requests-list",
                icon_svg=icon,
                staff_required=True,
                active_prefix="/smallstack/approvals/",
            )
            # The console is LoginRequired + eligibility-scoped (F-01), so a
            # non-staff assignee can use it — but the ADMIN section is staff-only in
            # the sidebar template, so she had NO nav entry: no active state, and no
            # way back to her queue after navigating away. The persona the docs
            # market reached the console only from a bell row or a pasted URL.
            # Registered separately, and hidden from staff so they do not see
            # "Approvals" twice. (F-46.)
            nav.register(
                section="app",
                label="Approvals",
                url_name="approvals/requests-list",
                icon_svg=icon,
                auth_required=True,
                visible=lambda request: not getattr(
                    getattr(request, "user", None), "is_staff", False
                ),
                active_prefix="/smallstack/approvals/",
                order=5,
            )
        except Exception:  # noqa: BLE001
            logger.warning("approvals: nav registration failed", exc_info=True)

        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import ApprovalsDashboardWidget

            dashboard.register(ApprovalsDashboardWidget())
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("approvals: dashboard widget registration failed", exc_info=True)

        try:
            from apps.smallstack import monitors

            from .monitors import ApprovalsFanoutMonitor, ApprovalsService

            monitors.register_service(ApprovalsService())
            monitors.register_monitor(ApprovalsFanoutMonitor())
        except ImportError:
            pass  # status surface not installed — optional
        except Exception:  # noqa: BLE001
            logger.warning("approvals: status monitor registration failed", exc_info=True)
