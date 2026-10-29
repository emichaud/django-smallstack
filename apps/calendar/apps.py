"""AppConfig for the calendar app."""

from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("smallstack.calendar")

CALENDAR_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">'
    '<path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5'
    'c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z"/></svg>'
)


class CalendarConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # Namespaced label (smallstack_runbook / smallstack_blog precedent) so a
    # downstream app labelled "calendar" can coexist. Final before 0001.
    name = "apps.calendar"
    label = "smallstack_calendar"
    verbose_name = "Calendar"

    help_content_dir = "content"
    help_section_slug = "calendar"
    help_section_title = "Calendar"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_CALENDAR_ENABLED", True):
            return

        try:
            from apps.smallstack.navigation import nav

            # A user app, beside Runbook and My blogs in the main section.
            nav.register(
                section="main",
                label="Calendar",
                url_name="calendar_index",
                icon_svg=CALENDAR_ICON,
                auth_required=True,
                order=7,
                active_prefix="/smallstack/calendar/",
            )
        except Exception:  # noqa: BLE001
            logger.warning("calendar: nav registration failed", exc_info=True)

        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import CalendarDashboardWidget

            dashboard.register(CalendarDashboardWidget())
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("calendar: dashboard widget registration failed", exc_info=True)

        if getattr(settings, "SMALLSTACK_MCP_ENABLED", True):
            try:
                from .mcp_tools import register_calendar_tools

                register_calendar_tools()
            except Exception:  # noqa: BLE001
                logger.exception("calendar: MCP tool registration failed")
