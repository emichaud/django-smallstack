"""RunbookDashboardWidget — at-a-glance runbook stats on /smallstack/.

Cheap to render: a couple of counts. Surfaces how much living documentation the
project holds and links straight to the runbook dashboard.
"""

from __future__ import annotations

from apps.smallstack.displays import DashboardWidget


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


class RunbookDashboardWidget(DashboardWidget):
    title = "Runbook"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M6 2a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6H6z'
        "m7 1.5L18.5 9H13V3.5zM8 12h8v2H8v-2zm0 4h8v2H8v-2z"
        '"/></svg>'
    )
    order = 32
    url_name = "runbook:dashboard"

    def get_data(self, model_class=None) -> dict:
        from .models import Document, Runbook

        n_runbooks = Runbook.objects.count()
        n_docs = Document.objects.filter(is_archived=False).count()

        if n_runbooks == 0:
            return {
                "headline": "No runbooks",
                "detail": "Create one to start documenting.",
                "status": "degraded",
            }

        return {
            "headline": _plural(n_runbooks, "runbook"),
            "detail": f"{_plural(n_docs, 'document')}",
            "status": "operational",
        }

    def get_api_extras(self, model_class=None) -> dict:
        from .models import Document, Runbook, Section

        return {
            "documents": Document.objects.filter(is_archived=False).count(),
            "runbooks": Runbook.objects.count(),
            "sections": Section.objects.count(),
        }
