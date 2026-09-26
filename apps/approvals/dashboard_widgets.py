"""Dashboard widget — the pending-approvals count on /smallstack/."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.smallstack.displays import DashboardWidget

from .models import ApprovalRequest


class ApprovalsDashboardWidget(DashboardWidget):
    title = "Approvals"
    icon = (
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">'
        '<path d="M12 1 3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z'
        'm-2 16-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
    )
    order = 47
    url_name = "approvals/requests-list"

    def get_data(self, model_class: Any = None) -> dict[str, Any]:
        # `actionable()` — pending minus overdue — is the same definition the
        # queue and its stat card use. Counting raw `status="pending"` made the
        # widget disagree with the page it links to until someone loaded that
        # page and the lazy sweep fired (F-19). Deliberately NOT mark_expired():
        # the dashboard must not pay the fan-out cost (F-12).
        pending = ApprovalRequest.objects.actionable()
        count = pending.count()
        if not count:
            return {"headline": "0 pending", "detail": "All decided", "status": "ok"}
        oldest = pending.order_by("created_at").first()
        waited = ""
        if oldest is not None:
            days = (timezone.now() - oldest.created_at).days
            waited = f"oldest waiting {days}d" if days else "oldest under a day"
        return {
            "headline": f"{count} pending",
            "detail": waited,
            "status": "warning",
        }
