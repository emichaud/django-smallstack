"""SearchDashboardWidget — at-a-glance status on /smallstack/.

Cheap to render — counts registered views and the active backend name.
Status flips to "degraded" if the backend isn't a native FTS (fallback
on MySQL) or if zero CRUDViews have opted in.
"""

from __future__ import annotations

from apps.smallstack.displays import DashboardWidget


class SearchDashboardWidget(DashboardWidget):
    title = "Search"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16'
        ' c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14'
        ' 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/>'
        "</svg>"
    )
    order = 33
    url_name = "search:page"

    def get_data(self, model_class=None) -> dict:
        from .backends import get_backend
        from .registry import view_count

        backend = get_backend()
        n = view_count()
        is_native = "fts" in backend.name or "postgres" in backend.name

        if n == 0:
            return {
                "headline": "0 indexed",
                "detail": "No CRUDView has enable_search=True yet.",
                "status": "degraded",
            }

        headline = f"{n} indexed model{'s' if n != 1 else ''}"

        if not is_native:
            return {
                "headline": headline,
                "detail": f"Backend: {backend.name} (slow at scale)",
                "status": "degraded",
            }

        return {
            "headline": headline,
            "detail": f"Backend: {backend.name}",
            "status": "operational",
        }

    def get_api_extras(self, model_class=None) -> dict | None:
        from .backends import get_backend
        from .registry import all_views, view_count

        return {
            "indexed_model_count": view_count(),
            "backend": get_backend().name,
            "models": [v.model_label for v in all_views()],
        }
