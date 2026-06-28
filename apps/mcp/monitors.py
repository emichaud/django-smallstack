"""Status monitor for the MCP server.

A cheap liveness probe (tools are registered) — NOT the full ``mcp_doctor``
self-test, which stays on the Health page. Registered from ``apps.py:ready()``.
"""

from __future__ import annotations

from apps.smallstack.monitors import CheckResult, Monitor, Service

_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    '<path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm1 17.93V18a2 2 0 0 0-2-2v-1a2 2 0 0 1-2-2H7.09a8 8 0 0 1 '
    '6.91-6.91V8h-1V6h2v-.93A8 8 0 0 1 19 12a8 8 0 0 1-6 7.93z"/></svg>'
)


class McpService(Service):
    key: str = "mcp"
    title: str = "MCP Server"
    description: str = "JSON-RPC tools, OAuth, and the Model Context Protocol endpoint."
    icon: str = _ICON
    order: int = 30
    public: bool = False
    category: str = "core"  # platform surface → the "Site" tier
    detail_url_name: str | None = "mcp_admin:health"  # deep diagnostics (mcp_doctor)


class McpMonitor(Monitor):
    key: str = "mcp"
    service: str = "mcp"
    title: str = "Tool registry"
    order: int = 10
    public: bool = False
    detail_url_name: str | None = "heartbeat:monitor_detail"
    detail_url_kwargs: dict | None = {"monitor_key": "mcp"}

    def check(self) -> CheckResult:
        from apps.mcp.server import TOOL_REGISTRY

        if not TOOL_REGISTRY:
            return CheckResult.down("No MCP tools registered")
        count = len(TOOL_REGISTRY)
        return CheckResult.up(note=f"{count} tool{'' if count == 1 else 's'}")

    def inventory(self) -> dict:
        """Live: the registered MCP tools behind the server."""
        from apps.mcp.server import TOOL_REGISTRY

        items = [{"label": name, "meta": (td.description or "")[:90]} for name, td in sorted(TOOL_REGISTRY.items())]
        n = len(items)
        return {"ok": bool(TOOL_REGISTRY), "summary": f"{n} tool{'' if n == 1 else 's'}", "items": items}
