"""Dashboard widgets surfaced by the MCP module.

Lands on /smallstack/ next to Backups, Help, Activity, etc. The widget is
intentionally cheap — it does NOT run mcp_doctor's full self-test (no DB
writes, no HTTP) so loading the dashboard stays snappy. It picks the
single signal that's most useful at a glance:

  headline:  N tools registered (or "0 tools" if empty)
  detail:    "All checks passing", "N warning(s)" — depending on registry
             vs orphan-file diff (the same heuristic mcp_doctor uses).
  status:    "operational" | "degraded"  → drives the headline color via
             the existing .widget-status-* CSS rules used by Heartbeat.

Clicking the widget jumps to /smallstack/mcp/ (the Health page).
"""

from __future__ import annotations

from typing import Any

from apps.smallstack.displays import DashboardWidget


class MCPDashboardWidget(DashboardWidget):
    title = "MCP"
    # Globe-with-orbit icon — evokes "protocol" / "AI" without being a
    # generic robot. Matches the inline-SVG palette of the other widgets.
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm0-14a6 6 0 1 0 6 6 6 6 0 0 0-6-6zm0 10a4 4 0 1 1 4-4 4 4 0 0 1-4 4z"/>'  # noqa: E501
        "</svg>"
    )
    order = 35  # between Backups (40) and a future Activity widget
    url_name = "mcp_admin:health"

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from apps.mcp.server import TOOL_REGISTRY

        tool_count = len(TOOL_REGISTRY)
        orphan_count = self._orphan_count()

        # Headline: tool count is the single most actionable number on
        # the dashboard. "0 tools" is itself a useful signal — somebody's
        # MCP server isn't wired up yet.
        if tool_count == 0:
            headline = "No tools"
        else:
            headline = f"{tool_count} tool{'s' if tool_count != 1 else ''}"

        # Detail + status: orphan files are the canonical "you have a
        # problem" signal (same heuristic mcp_doctor uses). When the
        # registry is empty AND there are no orphans, that's an
        # uninstalled-but-OK state, not a warning.
        if orphan_count:
            detail = f"{orphan_count} unregistered file{'s' if orphan_count != 1 else ''}"
            status = "degraded"
        elif tool_count == 0:
            detail = "Awaiting enable_mcp"
            status = "operational"
        else:
            detail = "All checks passing"
            status = "operational"

        return {
            "headline": headline,
            "detail": detail,
            "status": status,
        }

    def get_api_extras(self, model_class: type | None = None) -> dict[str, Any] | None:
        """Richer payload for API consumers (/api/dashboard/widgets/).

        The HTML widget renders the headline + detail only; everything
        below surfaces to anyone polling the JSON endpoint without
        running mcp_doctor themselves.
        """
        from apps.mcp.server import TOOL_REGISTRY

        tools = list(TOOL_REGISTRY.values())
        return {
            "tool_count": len(tools),
            "write_tool_count": sum(1 for t in tools if t.write),
            "read_tool_count": sum(1 for t in tools if not t.write),
            "orphan_count": self._orphan_count(),
        }

    @staticmethod
    def _orphan_count() -> int:
        """Reuse mcp_doctor's orphan-finder, but only for the count.

        Cheap — it just compares already-loaded CRUDView class source
        files against a tree scan. Same machinery that powers the WARN
        in the Health page; no extra cost.
        """
        try:
            from apps.mcp.management.commands.mcp_doctor import Command

            return len(Command()._find_unregistered_optins())
        except Exception:
            return 0
