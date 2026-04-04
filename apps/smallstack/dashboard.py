"""Dashboard widget registry and data layer.

Two sources of widgets feed the SmallStack dashboard:

1. Explorer widgets — admin classes declare `explorer_dashboard_widgets` and
   the Explorer registry discovers them automatically.

2. Standalone widgets — apps without an Explorer model register via
   `dashboard.register(widget)` in their AppConfig.ready().

The data layer (`get_widget_contexts`) returns rich context dicts that can
be consumed by the default dashboard view, a custom view via the mixin, or
an API endpoint.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe

if TYPE_CHECKING:
    from django.db.models import Model

    from apps.explorer.registry import ModelInfo

    from .displays import DashboardWidget

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standalone registry
# ---------------------------------------------------------------------------


_standalone_widgets: list[DashboardWidget] = []


def register(widget: DashboardWidget) -> None:
    """Register a standalone DashboardWidget (no Explorer model)."""
    _standalone_widgets.append(widget)


def get_standalone_widgets() -> list[DashboardWidget]:
    """Return all standalone-registered widgets."""
    return list(_standalone_widgets)


# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------


def _resolve_url(widget: DashboardWidget, model_info: ModelInfo | None) -> str | None:
    """Resolve a widget's target URL.

    Priority: widget.url_name > Explorer list URL (if model_info) > None.
    """
    if widget.url_name:
        try:
            return reverse(widget.url_name, kwargs=widget.url_kwargs or None)
        except NoReverseMatch:
            logger.warning("Dashboard widget %s: cannot reverse %s", widget.title, widget.url_name)
            return None
    if model_info is not None:
        try:
            return model_info._reverse(f"{model_info.url_base}-list")
        except NoReverseMatch:
            return None
    return None


def get_widget_contexts(
    group: str | None = None,
    app: str | None = None,
    model: type[Model] | None = None,
    dashboard_only: bool = False,
) -> list[dict]:
    """Return widget contexts sorted by order, optionally filtered.

    Args:
        group: Restrict to widgets whose group matches (case-insensitive).
        app: Restrict to widgets on models with this app_label.
        model: Restrict to widgets on this model class.
        dashboard_only: If True, drop widgets with on_dashboard=False.
                        Used by the main /smallstack/ dashboard to avoid
                        crowding; filtered views (group/app) show all.

    Returns:
        List of dicts with keys: widget, data, url, model_info, group,
        app_label, model_name.
    """
    from apps.explorer.registry import explorer

    contexts = []

    # Explorer-sourced widgets
    for widget, info in explorer.get_dashboard_widgets():
        if dashboard_only and not widget.on_dashboard:
            continue
        if model is not None and info.model_class is not model:
            continue
        if app is not None and info.app_label != app:
            continue
        if group is not None and info.group.lower() != group.lower():
            continue
        try:
            data = widget.get_data(model_class=info.model_class)
        except Exception:
            logger.warning("Dashboard widget %s failed", widget.title, exc_info=True)
            continue
        contexts.append(
            {
                "widget": widget,
                "data": data,
                "url": _resolve_url(widget, info),
                "model_info": info,
                "group": info.group,
                "app_label": info.app_label,
                "model_name": info.model_name,
            }
        )

    # Standalone widgets (skipped when filtering by app/model)
    if app is None and model is None:
        for widget in get_standalone_widgets():
            if dashboard_only and not widget.on_dashboard:
                continue
            if group is not None:
                if not widget.group or widget.group.lower() != group.lower():
                    continue
            try:
                data = widget.get_data()
            except Exception:
                logger.warning("Dashboard widget %s failed", widget.title, exc_info=True)
                continue
            contexts.append(
                {
                    "widget": widget,
                    "data": data,
                    "url": _resolve_url(widget, None),
                    "model_info": None,
                    "group": widget.group,
                    "app_label": None,
                    "model_name": None,
                }
            )

    contexts.sort(key=lambda c: c["widget"].order)

    # Mark icons safe for template rendering
    for ctx in contexts:
        ctx["icon_safe"] = mark_safe(ctx["widget"].icon)

    return contexts


def serialize_widget_context(ctx: dict) -> dict:
    """Convert a widget context into a JSON-serializable dict (for API use).

    Merges any get_api_extras() output into the "data" field, so API
    consumers get both the display-ready fields and any richer extras.
    """
    w = ctx["widget"]
    data = dict(ctx["data"])
    info = ctx["model_info"]
    try:
        extras = w.get_api_extras(model_class=info.model_class if info else None)
    except Exception:
        logger.warning("Dashboard widget %s get_api_extras failed", w.title, exc_info=True)
        extras = None
    if extras:
        data.update(extras)
    return {
        "title": w.title,
        "icon": w.icon,
        "order": w.order,
        "widget_type": w.widget_type,
        "span": w.span,
        "on_dashboard": w.on_dashboard,
        "url": ctx["url"],
        "data": data,
        "group": ctx["group"],
        "app_label": ctx["app_label"],
        "model_name": ctx["model_name"],
    }


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


def _build_api_view():
    """Lazily build the api_view-decorated endpoint (avoids import-time cycle)."""
    from .api import api_view

    @api_view(methods=["GET"], require_staff=True)
    def api_widgets(request):
        """GET /api/dashboard/widgets/?group=X&app=Y&dashboard_only=1"""
        group = request.GET.get("group") or None
        app = request.GET.get("app") or None
        dashboard_only = request.GET.get("dashboard_only") == "1"
        contexts = get_widget_contexts(group=group, app=app, dashboard_only=dashboard_only)
        return {"widgets": [serialize_widget_context(c) for c in contexts]}

    return api_widgets


api_widgets = _build_api_view()


# ---------------------------------------------------------------------------
# Presentation: mixin for views
# ---------------------------------------------------------------------------


class DashboardWidgetsMixin:
    """Adds `widgets` to template context.

    Optional class attributes:
        widget_group: Filter to this group.
        widget_app: Filter to this app_label.
        widget_model: Filter to this model class.
        widget_dashboard_only: Drop widgets with on_dashboard=False.
            Defaults to True when no filter is set (main dashboard),
            False when any filter is active (filtered view shows all).
    """

    widget_group: str | None = None
    widget_app: str | None = None
    widget_model = None
    widget_dashboard_only: bool | None = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        dashboard_only = self.widget_dashboard_only
        if dashboard_only is None:
            # Default: on_dashboard filter applies only to unfiltered view
            dashboard_only = not (self.widget_group or self.widget_app or self.widget_model)
        context["widgets"] = get_widget_contexts(
            group=self.widget_group,
            app=self.widget_app,
            model=self.widget_model,
            dashboard_only=dashboard_only,
        )
        return context
