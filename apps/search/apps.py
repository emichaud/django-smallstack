"""AppConfig for the search module.

Mirrors apps.api / apps.mcp: a thin observation/registration layer that
exposes the search backend through CRUDView's enable_search flag, the
MCP server, a topbar omnibar, a dashboard widget, and a sidebar entry.

The runtime search backend itself (SQLiteFTSBackend / PostgresFTSBackend
/ FallbackBackend) is selected automatically at startup based on the
database engine — see backends/__init__.py:get_backend().
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger("smallstack.search")


class SearchConfig(AppConfig):
    name = "apps.search"
    label = "search"
    verbose_name = "Search"

    def ready(self) -> None:
        # Step 1: walk every CRUDView in the registry and register the
        # ones opted into search. Same pattern as apps.mcp registering
        # MCP tools from enable_mcp CRUDViews — see apps/mcp/apps.py.
        try:
            from apps.smallstack.crud import CRUDView

            from .registry import register
        except Exception:
            logger.exception("Search registry import failed; skipping registration")
            return

        for view_cls in list(CRUDView._registry.values()):
            if getattr(view_cls, "enable_search", False):
                try:
                    register(view_cls)
                except Exception:
                    logger.exception("Failed to register search for %s", view_cls)

        # Step 2: hook signals so the index stays current as objects are
        # saved or deleted on any registered model.
        try:
            from . import signals  # noqa: F401  (registers handlers)
        except Exception:
            logger.exception("Failed to wire search signal handlers")

        # Step 3: register MCP tools for every opted-in CRUDView. The
        # mcp_tools factory is a no-op if apps.mcp isn't installed.
        try:
            from .mcp_tools import register_search_tools

            register_search_tools()
        except Exception:
            logger.exception("Failed to register search MCP tools")

        # Step 4: dashboard widget + sidebar entry (best-effort).
        try:
            from apps.smallstack import dashboard
            from apps.smallstack.navigation import nav

            from .dashboard_widgets import SearchDashboardWidget

            dashboard.register(SearchDashboardWidget())
            nav.register(
                section="admin",
                label="Search",
                url_name="search:page",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16'
                    ' c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14 5 11.99 5 9.5'
                    'S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>'
                    "</svg>"
                ),
                staff_required=True,
                order=33,  # before MCP (35) — search is more general
            )
        except Exception:
            logger.exception("Failed to register search widget/nav")
