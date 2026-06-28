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
        # This only populates an in-memory dict — no DB queries fire.
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

        # Step 1.5: hook FTS index creation to post_migrate.
        # Django warns when DB queries run during AppConfig.ready, so
        # we defer ensure_index until migrate completes. On normal
        # invocations (runserver, manage.py commands) the indexes
        # already exist from a prior `make setup` / `manage.py migrate`,
        # so deferring is safe.
        try:
            from django.db.models.signals import post_migrate

            from .registry import ensure_all_indexes

            def _ensure_indexes_after_migrate(sender, **kwargs):
                # The handler runs once per AppConfig-with-models on
                # every `migrate` invocation. ensure_index is idempotent
                # (CREATE VIRTUAL TABLE IF NOT EXISTS), so repeats are
                # cheap and correct.
                ensure_all_indexes()

            post_migrate.connect(
                _ensure_indexes_after_migrate,
                dispatch_uid="apps.search.ensure_all_indexes",
                weak=False,  # don't let GC unregister the closure
            )
        except Exception:
            logger.exception("Failed to hook post_migrate for search indexes")

        # Step 2: hook signals so the index stays current as objects are
        # saved or deleted on any registered model.
        try:
            from . import signals  # noqa: F401  (registers handlers)
        except Exception:
            logger.exception("Failed to wire search signal handlers")

        # Step 3: register MCP tools for every opted-in CRUDView. The
        # mcp_tools factory is a no-op if apps.mcp isn't installed — and we skip it
        # entirely when MCP is turned off site-wide (SMALLSTACK_MCP_ENABLED).
        from django.conf import settings

        if getattr(settings, "SMALLSTACK_MCP_ENABLED", True):
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
                # Lifted to authenticated (was staff-only) in v0.11.8.
                # The page enforces per-view access via the registry, so
                # non-staff signed-in users land here and see whatever the
                # SearchAccess.AUTHENTICATED tier allows (plus help docs).
                staff_required=False,
                order=33,  # before MCP (35) — search is more general
            )
        except Exception:
            logger.exception("Failed to register search widget/nav")

        # Step 5: register the search status monitor (pluggable status framework).
        try:
            from apps.smallstack import monitors

            from .monitors import SearchMonitor, SearchService

            monitors.register_service(SearchService())
            monitors.register_monitor(SearchMonitor())
        except Exception:
            logger.exception("Failed to register search status monitor")
