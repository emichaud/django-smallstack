"""Status monitor for the REST API surface.

A cheap liveness probe (the API schema URL resolves) — NOT the full ``api_doctor``
report, which stays on the Health page. Registered with the pluggable status
framework from ``apps.py:ready()``.
"""

from __future__ import annotations

from apps.smallstack.monitors import CheckResult, Monitor, Service

_ICON = (
    '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">'
    '<path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z"/></svg>'
)


class ApiService(Service):
    key: str = "api"
    title: str = "REST API"
    description: str = "OpenAPI schema, Swagger / ReDoc, and CRUD endpoints."
    icon: str = _ICON
    order: int = 20
    public: bool = False
    category: str = "core"  # platform surface → the "Site" tier
    detail_url_name: str | None = "api_admin:health"  # deep diagnostics (api_doctor)


class ApiMonitor(Monitor):
    key: str = "api"
    service: str = "api"
    title: str = "API surface reachable"
    order: int = 10
    public: bool = False
    detail_url_name: str | None = "heartbeat:monitor_detail"
    detail_url_kwargs: dict | None = {"monitor_key": "api"}

    def check(self) -> CheckResult:
        from django.urls import NoReverseMatch, reverse

        from apps.smallstack.api import _api_registry

        try:
            reverse("api-schema")
        except NoReverseMatch:
            return CheckResult.down("API schema URL not wired")
        count = len(_api_registry)
        return CheckResult.up(note=f"{count} endpoint{'' if count == 1 else 's'}")

    def inventory(self) -> dict:
        """Live: the REST resources exposed by ``enable_api`` CRUDViews."""
        from django.urls import NoReverseMatch, reverse

        from apps.smallstack.api import _api_registry

        ok = True
        try:
            reverse("api-schema")
        except NoReverseMatch:
            ok = False
        items = []
        for cfg, name in _api_registry:
            try:
                url = reverse(name)
            except NoReverseMatch:
                url = None
            items.append({"label": cfg.model.__name__, "meta": str(cfg.model._meta.verbose_name_plural), "url": url})
        n = len(items)
        return {"ok": ok, "summary": f"{n} endpoint{'' if n == 1 else 's'}", "items": items}
