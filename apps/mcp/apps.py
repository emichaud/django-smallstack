"""AppConfig for the MCP (Model Context Protocol) server.

CRITICAL: `label = "mcp_server"` (not "mcp"). The `mcp` PyPI package owns the
"mcp" Python module name, and Django keys app config by label — using "mcp"
collides with importable name and silently breaks signal wiring.
"""

import importlib
import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger("smallstack.mcp")


class MCPConfig(AppConfig):
    name = "apps.mcp"
    label = "mcp_server"
    verbose_name = "Model Context Protocol"

    def ready(self):
        # Honor the site-wide MCP switch: with MCP off, register nothing — no
        # tools, autodiscovery, nav, dashboard widget, or status monitor. The
        # /mcp endpoint + OAuth routes are unregistered in config/urls.py too.
        if not getattr(settings, "SMALLSTACK_MCP_ENABLED", True):
            return

        # Step 1: import any project-supplied tool modules so their @tool
        # decorators self-register against the singleton server.
        for path in getattr(settings, "MCP_TOOL_MODULES", []) or []:
            try:
                importlib.import_module(path)
            except Exception:
                logger.exception("Failed to import MCP_TOOL_MODULES entry %s", path)

        # Step 2: autodiscover. Django auto-imports models.py and (via the
        # admin's own autodiscover) admin.py, but it does NOT auto-import
        # views.py. CRUDView subclasses defined in views.py would therefore
        # never trigger __init_subclass__ before we walk the registry below.
        # Mirror the admin.autodiscover pattern and try-import every app's
        # views.py + mcp_tools.py at startup. Failures are swallowed.
        if getattr(settings, "MCP_AUTODISCOVER", True):
            self._autodiscover_apps(("views", "mcp_tools"))

        # Step 3: walk the CRUDView registry and emit factory tools for
        # anything opted in via enable_mcp = True.
        try:
            from apps.smallstack.crud import CRUDView

            from .factory import register_mcp_tools_from_crudview
        except ImportError:
            return

        for view_cls in list(CRUDView._registry.values()):
            if getattr(view_cls, "enable_mcp", False):
                try:
                    register_mcp_tools_from_crudview(view_cls)
                except Exception:
                    logger.exception("Failed to register MCP tools for %s", view_cls)

        # Step 4: register the at-a-glance dashboard widget so /smallstack/
        # surfaces MCP next to Backups, Help, etc. Cheap — no DB hits or
        # HTTP, just a registry count + the orphan-files heuristic.
        try:
            from apps.smallstack import dashboard

            from .dashboard_widgets import MCPDashboardWidget

            dashboard.register(MCPDashboardWidget())
        except Exception:
            logger.exception("Failed to register MCP dashboard widget")

        # Step 5: register the staff-only "MCP" sidebar entry. Lands users
        # on the Health page; internal tabs surface Tools and Activity.
        try:
            from apps.smallstack.navigation import nav

            nav.register(
                section="admin",
                label="MCP",
                url_name="mcp_admin:health",
                icon_svg=(
                    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
                    '<path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 17.93V18a2 2 0 0 0-2-2v-1a2 2 0 0 1-2-2H7.09a8 8 0 0 1 6.91-6.91V8h-1V6h2v-.93A8 8 0 0 1 19 12a8 8 0 0 1-6 7.93z"/>'  # noqa: E501
                    "</svg>"
                ),
                staff_required=True,
                order=35,
            )
        except Exception:
            logger.exception("Failed to register MCP sidebar entry")

        # Step 6: register the MCP status monitor (pluggable status framework).
        try:
            from apps.smallstack import monitors

            from .monitors import McpMonitor, McpService

            monitors.register_service(McpService())
            monitors.register_monitor(McpMonitor())
        except Exception:
            logger.exception("Failed to register MCP status monitor")

    def _autodiscover_apps(self, module_names: tuple[str, ...]) -> list[str]:
        """Import `<app>.<module>` for every installed app and module name.

        Returns the list of dotted paths that were successfully imported.
        Missing modules (ImportError on the dotted path itself) are silently
        skipped — most apps won't have a mcp_tools.py for instance. Errors
        DURING import (syntax errors, runtime failures) are logged but never
        re-raised; AppConfig.ready() crashing would take the whole process
        down.
        """
        from django.apps import apps as django_apps

        imported: list[str] = []
        for app_config in django_apps.get_app_configs():
            if app_config.label == self.label:
                continue
            for mod in module_names:
                dotted = f"{app_config.name}.{mod}"
                try:
                    importlib.import_module(dotted)
                    imported.append(dotted)
                except ImportError:
                    pass
                except Exception:
                    logger.warning("MCP autodiscover failed to import %s", dotted, exc_info=True)
        return imported
