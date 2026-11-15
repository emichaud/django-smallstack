from __future__ import annotations

from typing import Any

from apps.smallstack.displays import DashboardWidget


class AccessWidget(DashboardWidget):
    """Findings that need a look, on the /smallstack/ dashboard."""

    title = "Access"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16-4-4 '
        '1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
    )
    order = 35
    url_name = "access:index"

    def visible_to(self, user: Any) -> bool:
        from .services import can_read_access

        return can_read_access(user)

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from .registry import run_checks

        findings = run_checks()
        worst = [f for f in findings if f.severity in ("danger", "warning")]
        if worst:
            return {
                "headline": f"{len(worst)} finding{'s' if len(worst) != 1 else ''}",
                "detail": worst[0].title,
                "status": "error" if worst[0].severity == "danger" else "warning",
            }
        return {"headline": "No findings", "detail": "Least privilege holds", "status": "ok"}
