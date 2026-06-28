"""Status monitor for the search subsystem.

A cheap liveness probe (models are indexed) — NOT the full ``search_doctor``
report. Registered from ``apps.py:ready()``.
"""

from __future__ import annotations

from apps.smallstack.monitors import CheckResult, Monitor, Service

_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    '<path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16 c1.61 0 3.09-.59 '
    '4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 '
    '9.5 11.99 14 9.5 14z"/></svg>'
)


class SearchService(Service):
    key: str = "search"
    title: str = "Search"
    description: str = "Full-text search index over registered models."
    icon: str = _ICON
    order: int = 40
    public: bool = False
    category: str = "core"  # platform surface → the "Site" tier
    detail_url_name: str | None = "search:page"


class SearchMonitor(Monitor):
    key: str = "search"
    service: str = "search"
    title: str = "Search index"
    order: int = 10
    public: bool = False
    detail_url_name: str | None = "heartbeat:monitor_detail"
    detail_url_kwargs: dict | None = {"monitor_key": "search"}

    def check(self) -> CheckResult:
        from apps.search.registry import _search_registry

        if not _search_registry:
            return CheckResult.down("No models indexed for search")
        count = len(_search_registry)
        return CheckResult.up(note=f"{count} indexed model{'' if count == 1 else 's'}")

    def inventory(self) -> dict:
        """Live: the models indexed for full-text search."""
        from apps.search.registry import _search_registry

        items = []
        for label, iv in sorted(_search_registry.items()):
            try:
                name = str(iv.model._meta.verbose_name_plural).title()
            except Exception:  # noqa: BLE001
                name = label
            items.append({"label": name, "meta": label})
        n = len(items)
        return {"ok": bool(_search_registry), "summary": f"{n} model{'' if n == 1 else 's'}", "items": items}
