"""Scheduler app configuration.

``ready()`` autodiscovers ``@scheduled`` declarations (via each app's
``schedules.py`` / ``tasks.py``) and reconciles them into the DB. Registration
of nav/dashboard/status surfaces (P2) is added here too. Everything is
best-effort: a failure to sync or register must never take down app startup,
and DB-touching work is skipped when the tables don't exist yet (e.g. during
the very migrate that creates them).
"""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

logger = logging.getLogger("smallstack.scheduler")


class SchedulerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.scheduler"
    verbose_name = "Scheduler"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_SCHEDULER_ENABLED", True):
            return

        # Import @scheduled declarations from every app's schedules.py / tasks.py.
        # tasks.py is already imported elsewhere, but discovering it here too is
        # harmless and covers apps that keep schedules beside their tasks.
        try:
            from apps.smallstack.autodiscover import autodiscover_app_modules

            autodiscover_app_modules(("schedules", "tasks"), skip_label=self.label)
        except Exception:  # noqa: BLE001
            logger.warning("scheduler: autodiscovery failed", exc_info=True)

        # Reconcile code-declared schedules into the DB. Guarded: during the
        # initial migrate the scheduler tables don't exist yet.
        try:
            from .registry import sync_code_jobs

            sync_code_jobs()
        except (OperationalError, ProgrammingError):
            pass  # tables not migrated yet — normal on first boot / during migrate
        except Exception:  # noqa: BLE001
            logger.warning("scheduler: code-job sync failed", exc_info=True)

        # P2 surfaces (nav item, dashboard widget, status monitor) register here.
        self._register_surfaces()

    def _register_surfaces(self) -> None:
        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="Scheduler",
                url_name="scheduler:dashboard",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12'
                    'S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z'
                    'M12.5 7H11v6l5.25 3.15.75-1.23-4.5-2.67z"/></svg>'
                ),
                staff_required=True,
                order=25,
                active_prefix="/smallstack/scheduler/",
            )
        except Exception:  # noqa: BLE001 — never block startup on nav registration
            logger.warning("scheduler: nav registration failed", exc_info=True)

        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import SchedulerDashboardWidget

            dashboard.register(SchedulerDashboardWidget())
        except ImportError:
            pass  # surface module not present (P2) — optional
        except Exception:  # noqa: BLE001
            logger.warning("scheduler: dashboard widget registration failed", exc_info=True)

        try:
            from apps.smallstack import monitors

            from .monitors import SchedulerMonitor, SchedulerService

            monitors.register_service(SchedulerService())
            monitors.register_monitor(SchedulerMonitor())
        except ImportError:
            pass  # surface module not present (P2) — optional
        except Exception:  # noqa: BLE001
            logger.warning("scheduler: status monitor registration failed", exc_info=True)
