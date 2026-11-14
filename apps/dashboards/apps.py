"""AppConfig for dashboards — metrics, dashboards and KPI reports over @dataset."""

from __future__ import annotations

import logging
from typing import Any

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)

DASHBOARDS_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">'
    '<path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/></svg>'
)


GOALS_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">'
    '<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm0-14a6 6 0 1 0 0 12'
    ' 6 6 0 0 0 0-12zm0 10a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm0-6a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/></svg>'
)


class DashboardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboards"
    # Namespaced label (smallstack_runbook / smallstack_calendar precedent): a
    # downstream app labelled "dashboards" is common enough to plan for.
    label = "smallstack_dashboards"
    verbose_name = "Dashboards"

    help_content_dir = "content"
    help_section_slug = "dashboards"
    help_section_title = "Dashboards"

    def ready(self) -> None:
        if not getattr(settings, "SMALLSTACK_DASHBOARDS_ENABLED", True):
            return

        # Imported for their side effects: the built-in card types register
        # themselves; signals delete a replaced or orphaned picture.
        from . import components, datasets, signals  # noqa: F401
        from .models import GoalList
        from .snapshots import goal_list_rows, register_subject
        from .weeks import snapshot_user

        register_subject(GoalList, rows=goal_list_rows, user=snapshot_user, ready=lambda g: bool(g.goals()))

        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="main",
                label="Dashboards",
                url_name="dashboards_index",
                icon_svg=DASHBOARDS_ICON,
                auth_required=True,
                order=8,
                active_prefix="/smallstack/dashboards/",
            )
            # Goals: the numbers themselves — goal lists, the metrics behind
            # them, reports over periods. Its pages live under
            # /smallstack/dashboards/ too, so each entry names its own paths
            # (a tuple of prefixes; the longest match wins the highlight).
            nav.register(
                section="main",
                label="Goals",
                url_name="goals_index",
                icon_svg=GOALS_ICON,
                auth_required=True,
                order=9,
                active_prefix="/smallstack/goals/",
            )
            base = "/smallstack/dashboards/"
            submenus: dict[str, tuple[tuple[str, str, Any], ...]] = {
                "Goals": (
                    ("Overview", "goals_index", None),
                    ("Goal lists", "dashboards/goals-list", (f"{base}goals/", f"{base}g/")),
                    ("Metrics", "dashboards/metrics-list", (f"{base}metrics/", f"{base}m/")),
                    ("Reports", "dashboards/reports-list", (f"{base}reports/", f"{base}r/")),
                ),
                # The submenu (Activity precedent). "My dashboards" is also in the user menu.
                "Dashboards": (
                    ("Overview", "dashboards_index", None),
                    ("My dashboards", "dashboards_mine", f"{base}mine/"),
                    ("Components", "dashboards/components-list", f"{base}components/"),
                    ("Playlists", "dashboards/playlists-list", (f"{base}playlists/", f"{base}p/")),
                ),
            }
            for parent, entries in submenus.items():
                for order, (label, url_name, prefix) in enumerate(entries):
                    nav.register(
                        section="main",
                        label=label,
                        url_name=url_name,
                        parent=parent,
                        auth_required=True,
                        order=order,
                        active_prefix=prefix,
                        active_exact=prefix is None,
                    )
        except Exception:  # noqa: BLE001
            logger.warning("dashboards: nav registration failed", exc_info=True)

        try:
            from apps.smallstack.dashboard import set_dashboard_page

            from .views import AdminHomeView

            # /smallstack/ becomes an editable dashboard of the published widgets.
            set_dashboard_page(AdminHomeView.as_view())
        except Exception:  # noqa: BLE001
            logger.warning("dashboards: taking over the /smallstack/ page failed", exc_info=True)

        from .api import register_openapi_paths

        register_openapi_paths()

        if getattr(settings, "SMALLSTACK_MCP_ENABLED", True):
            try:
                from .mcp_tools import register_dashboard_tools

                register_dashboard_tools()
            except Exception:  # noqa: BLE001
                logger.exception("dashboards: MCP tool registration failed")

        # Defaults apps ship (their dashboard_defaults.py, like datasets.py), kept
        # in step after every migrate (defaults.sync_defaults).
        from django.db.models.signals import post_migrate
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("dashboard_defaults")
        post_migrate.connect(_sync_defaults_after_migrate, dispatch_uid="dashboards_sync_defaults")


def _sync_defaults_after_migrate(sender: Any, **kwargs: Any) -> None:
    """Once per migrate (the dashboards app's own signal, when every table
    exists): create and update the defaults apps ship. Off with
    ``SMALLSTACK_DASHBOARD_DEFAULTS_SYNC = False``; never fails a migrate."""
    if getattr(sender, "label", "") != "smallstack_dashboards":
        return
    if not getattr(settings, "SMALLSTACK_DASHBOARD_DEFAULTS_SYNC", True):
        return
    from .defaults import sync_defaults

    try:
        report = sync_defaults()
    except Exception:  # noqa: BLE001
        logger.exception("dashboards: syncing the app defaults failed")
        return
    for app, kind, key, outcome, detail in report.lines:
        if outcome in ("created", "updated", "parked", "restored", "error", "conflict"):
            log = logger.warning if outcome in ("error", "conflict") else logger.info
            log("dashboard default %s %s:%s:%s %s", outcome, app, kind, key, detail)
