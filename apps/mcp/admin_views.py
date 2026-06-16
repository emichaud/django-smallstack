"""Staff-only admin UI for the MCP subsystem.

Three pages plus one POST endpoint:

- Health (``mcp_admin:health``) — renders the same checks ``mcp_doctor``
  prints, as color-coded HTML cards.
- Tools (``mcp_admin:tools``) — browseable registry. Detail page shows
  full description + inputSchema.
- Activity (``mcp_admin:activity``) — recent /mcp requests, filtered out
  of apps.activity.RequestLog. Graceful banner if the activity app
  isn't installed.
- Self-test (``mcp_admin:self_test``) — POST-only. Mints + revokes a temp
  token, exercises tools/list / ping / notifications/initialized via the
  Django test client. Returns an htmx fragment.

The page-content code is intentionally thin: all the diagnostic work
lives on the existing ``Command`` class in mcp_doctor. We just rebind it
to an HTML surface.
"""

from __future__ import annotations

from typing import Any

from django.http import Http404
from django.views.generic import TemplateView, View

from apps.smallstack.mixins import StaffRequiredMixin


class _AdminBase(StaffRequiredMixin, TemplateView):
    """Common base — currently just composes the staff gate."""


class MCPAdminHealthView(_AdminBase):
    template_name = "mcp/admin/health.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.mcp.management.commands.mcp_doctor import Command

        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "health"

        # Rebind mcp_doctor's checks to an HTML surface — same exact
        # `_check_*` methods, same exact `report` shape. Only difference:
        # we skip `_self_test` here. It mints DB rows and makes HTTP calls,
        # which is fine for a CLI invocation but not for every page load
        # — it lives behind the POST endpoint instead.
        cmd = Command()
        report: list[dict] = []
        cmd._check_mcp_package(report)
        cmd._check_settings(report)
        cmd._check_registry(report)
        cmd._check_urls(report)
        cmd._check_tokens(report)
        cmd._check_apitoken_admin(report)
        ctx["report"] = report

        # Coarse summary numbers for the page header strip.
        ctx["pass_count"] = sum(1 for r in report if r["status"] == "PASS")
        ctx["warn_count"] = sum(1 for r in report if r["status"] == "WARN")
        ctx["fail_count"] = sum(1 for r in report if r["status"] == "FAIL")
        return ctx


class MCPAdminToolsView(_AdminBase):
    template_name = "mcp/admin/tools.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "tools"
        ctx["tools"] = []  # Phase 4 fills this in.
        return ctx


class MCPAdminToolDetailView(_AdminBase):
    template_name = "mcp/admin/tool_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        from apps.mcp.server import TOOL_REGISTRY

        name = self.kwargs["name"]
        if name not in TOOL_REGISTRY:
            raise Http404(f"No MCP tool named {name!r}")
        ctx["page"] = "tools"  # keep "Tools" tab active
        ctx["tool"] = TOOL_REGISTRY[name]
        return ctx


class MCPAdminActivityView(_AdminBase):
    template_name = "mcp/admin/activity.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["page"] = "activity"
        ctx["entries"] = []  # Phase 5 fills this in.
        ctx["activity_app_installed"] = self._activity_app_installed()
        return ctx

    @staticmethod
    def _activity_app_installed() -> bool:
        from django.apps import apps as django_apps

        return any(c.label == "activity" for c in django_apps.get_app_configs())


class MCPAdminSelfTestView(StaffRequiredMixin, View):
    """POST-only endpoint for the "Run self-test now" button. Phase 3."""

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        # Phase 3 wires this up. For now keep the stub honest: return 200
        # with a placeholder fragment so the htmx swap target gets cleared.
        from django.http import HttpResponse

        return HttpResponse("<p>(self-test not yet implemented)</p>")
