"""Dashboard widget for the API admin module.

Lands on ``/smallstack/`` next to the MCP widget. Cheap by design — it
runs the cheap subset of api_doctor's checks (no HTTP, no DB writes) so
the dashboard stays snappy. The headline is endpoint count; the detail
mirrors the highest-severity signal we can compute without making a
request (orphan files, threats over 24h once Phase 3 ships).
"""

from __future__ import annotations

from apps.smallstack.displays import DashboardWidget


class APIDashboardWidget(DashboardWidget):
    title = "API"
    # Three horizontal bars — "schema" / "endpoint list" / "swagger" all
    # iconize this way; reads as "API resource" without being a generic
    # cogwheel.
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/>'
        "</svg>"
    )
    order = 37  # one slot past MCP (35), before Backups (40)
    url_name = "api_admin:health"

    def get_data(self, model_class=None) -> dict:
        from apps.smallstack.api import _api_registry

        n = len(_api_registry)
        orphan_count = self._orphan_count()

        if n == 0:
            headline = "No endpoints"
        else:
            headline = f"{n} endpoint{'s' if n != 1 else ''}"

        if orphan_count:
            detail = f"{orphan_count} unregistered file{'s' if orphan_count != 1 else ''}"
            status = "degraded"
        elif n == 0:
            detail = "Awaiting enable_api"
            status = "operational"
        else:
            detail = "All checks passing"
            status = "operational"

        return {"headline": headline, "detail": detail, "status": status}

    def get_api_extras(self, model_class=None) -> dict | None:
        """Richer payload for /api/dashboard/widgets/ consumers."""
        from apps.smallstack.api import _api_registry

        return {
            "endpoint_count": len(_api_registry),
            "orphan_count": self._orphan_count(),
        }

    @staticmethod
    def _orphan_count() -> int:
        """Reuse api_doctor's orphan finder. Cheap — just a tree scan."""
        try:
            from apps.api.management.commands.api_doctor import Command

            return len(Command()._find_unregistered_optins())
        except Exception:
            return 0
