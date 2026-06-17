"""Staff-only admin UI for the REST API surface.

Two pages plus one POST endpoint:

- Health (``api_admin:health``) — renders the same checks ``api_doctor``
  prints, as color-coded HTML cards.
- Activity (``api_admin:activity``) — per-endpoint group-by + threat panel
  + filterable ``/api/*`` RequestLog table. (Implemented in Phase 3.)
- Self-test (``api_admin:self_test``) — POST-only. Mints + revokes a temp
  token, hits /api/schema/ + /api/schema/openapi.json + first list
  endpoint via the Django test client. Returns an htmx fragment.

The diagnostic work lives on the existing ``Command`` class in
api_doctor; admin views rebind it to an HTML surface.
"""

from __future__ import annotations

from typing import Any

from django.views.generic import TemplateView, View

from apps.smallstack.mixins import StaffRequiredMixin


class _AdminBase(StaffRequiredMixin, TemplateView):
    """Common base — staff gate plus shared context every page needs."""

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack.api import _api_registry

        ctx = super().get_context_data(**kwargs)
        ctx["endpoint_count"] = len(_api_registry)
        ctx.setdefault("warn_count", 0)
        ctx.setdefault("fail_count", 0)
        return ctx


class APIAdminHealthView(_AdminBase):
    template_name = "api/admin/health.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.api.management.commands.api_doctor import Command

        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "health"

        # Rebind api_doctor's checks to an HTML surface — same `_check_*`
        # methods, same `report` shape. Skip `_self_test` (HTTP + DB) —
        # it lives behind the POST endpoint.
        cmd = Command()
        report: list[dict] = []
        cmd._check_openapi_package(report)
        cmd._check_dependencies(report)
        cmd._check_registry(report)
        cmd._check_urls(report)
        cmd._check_swagger_redoc(report)
        cmd._check_openapi_validity(report)
        cmd._check_endpoint_consistency(report)
        cmd._check_orphans(report)
        cmd._check_token_auth(report)
        ctx["report"] = report

        ctx["pass_count"] = sum(1 for r in report if r["status"] == "PASS")
        ctx["warn_count"] = sum(1 for r in report if r["status"] == "WARN")
        ctx["fail_count"] = sum(1 for r in report if r["status"] == "FAIL")
        return ctx


class APIAdminActivityView(_AdminBase):
    """Placeholder for Phase 3 — Activity + Threat panel."""

    template_name = "api/admin/activity.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "activity"
        return ctx


class APIAdminSelfTestView(StaffRequiredMixin, View):
    """POST-only endpoint backing the "Run Self-Test" button.

    Mints a temp readonly APIToken, hits /api/schema/ + the OpenAPI JSON
    + the first list endpoint via the Django test client, revokes in a
    finally. Returns an htmx fragment.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        from django.shortcuts import render

        from apps.api.management.commands.api_doctor import Command

        cmd = Command()
        report: list[dict] = []
        try:
            cmd._self_test(report)
        except Exception as exc:  # noqa: BLE001 — any failure becomes a FAIL row
            report.append({"name": "Self-test", "status": "FAIL", "detail": str(exc)})

        entry = report[0] if report else {"status": "FAIL", "detail": "self-test produced no result"}
        return render(request, "api/admin/_self_test_result.html", {"entry": entry})
