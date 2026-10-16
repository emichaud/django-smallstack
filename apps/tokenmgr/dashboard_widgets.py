"""Token Manager dashboard widget.

Lands on /smallstack/ next to MCP / Backups / Help. Cheap — just a
single COUNT on APIToken filtered to the requester's scope.
"""

from __future__ import annotations

from typing import Any

from apps.smallstack.displays import DashboardWidget


class TokensDashboardWidget(DashboardWidget):
    title = "API Tokens"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M12.65 10A6 6 0 0 0 7 6a6 6 0 0 0 0 12 6 6 0 0 0 5.65-4H17v4h4v-4h2v-4H12.65zM7 14a2 2 0 1 1 0-4 2 2 0 0 1 0 4z"/>'  # noqa: E501
        "</svg>"
    )
    order = 38  # between MCP (35) and Backups (40)
    url_name = "tokenmgr:tokens-list"

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from apps.smallstack.models import APIToken

        qs = APIToken.objects.all()
        active = qs.filter(is_active=True).count()
        total = qs.count()
        revoked = total - active

        if total == 0:
            headline = "No tokens"
            detail = "Mint one for CI, Claude, or scripts"
            status = "operational"
        else:
            headline = f"{active} active"
            detail = f"of {total} total" + (f" ({revoked} revoked)" if revoked else "")
            status = "operational"
        return {"headline": headline, "detail": detail, "status": status}

    def get_api_extras(self, model_class: type | None = None) -> dict[str, Any] | None:
        from apps.smallstack.models import APIToken

        qs = APIToken.objects.all()
        return {
            "total_tokens": qs.count(),
            "active_tokens": qs.filter(is_active=True).count(),
            "revoked_tokens": qs.filter(is_active=False).count(),
            "by_access_level": {
                level: qs.filter(access_level=level).count()
                for level in ("readonly", "staff", "auth")
            },
        }
