"""Composability mixins for embedding Explorer into custom pages.

Usage — group page (dynamic from URL):

    class MyDashboardView(ExplorerGroupMixin, TemplateView):
        template_name = "myapp/dashboard.html"

Usage — group page (hardcoded):

    class MonitoringView(ExplorerGroupMixin, TemplateView):
        template_name = "myapp/monitoring.html"
        explorer_group = "Monitoring"

Usage — app page (dynamic from URL):

    class MyAppView(ExplorerAppMixin, TemplateView):
        template_name = "myapp/app_dashboard.html"

Usage — app page (hardcoded):

    class HeartbeatAppView(ExplorerAppMixin, TemplateView):
        template_name = "myapp/heartbeat_app.html"
        explorer_app = "heartbeat"

Usage — single model page (dynamic from URL):

    class MyModelView(ExplorerModelMixin, TemplateView):
        template_name = "myapp/model.html"

Usage — single model page (hardcoded):

    class HeartbeatView(ExplorerModelMixin, TemplateView):
        template_name = "myapp/heartbeats.html"
        explorer_app_label = "heartbeat"
        explorer_model_name = "heartbeat"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import Http404

if TYPE_CHECKING:
    from .registry import ExplorerSite


class _ExplorerSiteMixin:
    """Base mixin that resolves which ExplorerSite to query."""

    explorer_site: ExplorerSite | None = None

    def _get_site(self) -> ExplorerSite:
        if self.explorer_site:
            return self.explorer_site
        from .registry import explorer

        return explorer


class ExplorerGroupMixin(_ExplorerSiteMixin):
    """Mixin that populates template context with Explorer group data.

    Adds to context: group_name, models (list of ModelCardInfo), all_groups.

    Set ``explorer_group`` on the class to hardcode a group, or leave it
    unset to read from ``self.kwargs["group"]`` (URL parameter).

    Set ``explorer_site`` to use a child ExplorerSite instead of the default.
    """

    explorer_group: str | None = None  # Set to hardcode, or read from URL kwargs

    def get_explorer_group_name(self) -> str:
        if self.explorer_group:
            return self.explorer_group
        return self.kwargs["group"]

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        group_name = self.get_explorer_group_name()
        ctx = self._get_site().get_group_context(group_name)
        if not ctx:
            raise Http404(f"Group '{group_name}' not found in Explorer registry.")
        context.update(ctx.as_context())
        return context


class ExplorerAppMixin(_ExplorerSiteMixin):
    """Mixin that populates template context with Explorer app data.

    Adds to context: app_label, app_verbose_name, models (list of ModelCardInfo), all_apps.

    Set ``explorer_app`` on the class to hardcode an app_label, or leave it
    unset to read from ``self.kwargs["app_label"]`` (URL parameter).

    Set ``explorer_site`` to use a child ExplorerSite instead of the default.
    """

    explorer_app: str | None = None  # Set to hardcode, or read from URL kwargs

    def get_explorer_app_label(self) -> str:
        if self.explorer_app:
            return self.explorer_app
        return self.kwargs["app_label"]

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        app_label = self.get_explorer_app_label()
        ctx = self._get_site().get_app_context(app_label)
        if not ctx:
            raise Http404(f"App '{app_label}' not found in Explorer registry.")
        context.update(ctx.as_context())
        return context


class ExplorerModelMixin(_ExplorerSiteMixin):
    """Mixin that populates template context with Explorer model data.

    Adds to context: everything the crud_table template tag needs —
    object_list, list_fields, link_field, url_base, crud_actions, etc.

    Set ``explorer_app_label`` and ``explorer_model_name`` to hardcode,
    or leave unset to read from ``self.kwargs["app_label"]`` and
    ``self.kwargs["model_name"]``.

    Set ``explorer_site`` to use a child ExplorerSite instead of the default.
    """

    explorer_app_label: str | None = None
    explorer_model_name: str | None = None

    def get_explorer_app_label(self) -> str:
        if self.explorer_app_label:
            return self.explorer_app_label
        return self.kwargs["app_label"]

    def get_explorer_model_name(self) -> str:
        if self.explorer_model_name:
            return self.explorer_model_name
        return self.kwargs["model_name"]

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        app_label = self.get_explorer_app_label()
        model_name = self.get_explorer_model_name()
        ctx = self._get_site().get_model_context(app_label, model_name)
        if not ctx:
            raise Http404(f"Model '{app_label}.{model_name}' not found in Explorer registry.")
        context.update(ctx.as_context())
        return context
