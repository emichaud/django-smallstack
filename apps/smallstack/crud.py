"""Reusable CRUD library for SmallStack.

Generates Django generic CBVs + URL patterns from a single config class.

Usage:
    from apps.smallstack.crud import CRUDView, Action
    from apps.smallstack.mixins import StaffRequiredMixin

    class UserCRUDView(CRUDView):
        model = User
        fields = ["username", "email", "first_name", "last_name"]
        list_fields = ["username", "email"]
        url_base = "manage/users"
        paginate_by = 25
        mixins = [StaffRequiredMixin]

    # In urls.py:
    urlpatterns = [
        *UserCRUDView.get_urls(),
    ]
"""

import enum
import logging
import warnings
from typing import Any

from django import forms
from django.contrib import messages
from django.contrib.admin.models import LogEntry
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.db.models import Model, ProtectedError, QuerySet, RestrictedError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect as _redirect
from django.urls import path, reverse
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from . import transforms as _transforms
from .audit import CHANGE, DELETION

logger = logging.getLogger(__name__)

# Cap on how many row IDs a single bulk-action log line embeds in `extra`. The
# count in the message text is always exact; this just bounds how large one
# log/console line can get for a bulk action against thousands of rows.
_BULK_LOG_ID_CAP = 200

# ---------------------------------------------------------------------------
# Field preview helpers (delegated to transforms module)
# ---------------------------------------------------------------------------

# Re-export for backward compatibility — callers importing from crud.py still work.
_detect_format = _transforms._detect_format
_render_json_preview = _transforms._render_json_preview
_render_markdown_preview = _transforms._render_markdown_preview


class Action(enum.Enum):
    LIST = "list"
    CREATE = "create"
    DETAIL = "detail"
    UPDATE = "update"
    DELETE = "delete"


class BulkAction(enum.Enum):
    DELETE = "delete"
    UPDATE = "update"


# ---------------------------------------------------------------------------
# Internal base view classes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# List search & filter helpers (shared between HTML and API views)
# ---------------------------------------------------------------------------


def _apply_list_search(qs, request: HttpRequest, crud_config) -> QuerySet:
    """Apply ?q= text search to a queryset using configured search_fields.

    Text fields use __icontains.  Date/DateTime fields use smart date
    matching: "2026" → year, "2026-03" → year+month, "2026-03-15" → exact date.
    """
    import re

    from django.db import models as _m
    from django.db.models import Q

    search_fields = crud_config._resolve_search_fields()
    if not search_fields:
        return qs
    q = request.GET.get("q", "").strip()
    if not q:
        return qs

    # Pre-parse the query for date-like patterns
    date_filters: dict[str, Any] | None = None
    if re.fullmatch(r"\d{4}", q):
        date_filters = {"__year": int(q)}
    elif re.fullmatch(r"\d{4}-\d{1,2}", q):
        parts = q.split("-")
        date_filters = {"__year": int(parts[0]), "__month": int(parts[1])}
    elif re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", q):
        date_filters = {"__date": q}

    query = Q()
    for field in search_fields:
        try:
            model_field = crud_config.model._meta.get_field(field.split("__")[0])
        except Exception:
            model_field = None

        if isinstance(model_field, (_m.DateField, _m.DateTimeField)):
            if date_filters:
                field_q = Q()
                for suffix, val in date_filters.items():
                    field_q &= Q(**{f"{field}{suffix}": val})
                query |= field_q
        else:
            query |= Q(**{f"{field}__icontains": q})

    return qs.filter(query)


def _field_is_orderable(qs, field_path: str) -> bool:
    """Whether ``qs`` can actually be ordered by ``field_path``.

    Handles ``pk``, FK traversal (``category__name``), and query annotations.
    Returns False for computed / property columns that aren't DB fields — so a
    misconfigured ``ordering_fields`` (e.g. a display-only ``price_display``)
    degrades to "no sort" instead of raising ``FieldError`` when the queryset is
    evaluated (which would surface as a 500).
    """
    if field_path in qs.query.annotations:
        return True
    model = qs.model
    parts = field_path.split("__")
    for i, part in enumerate(parts):
        if part == "pk":
            field = model._meta.pk
        else:
            try:
                field = model._meta.get_field(part)
            except FieldDoesNotExist:
                return False
        if i < len(parts) - 1:  # more segments → must be a relation to keep walking
            model = getattr(field, "related_model", None)
            if model is None:
                return False
    return True


def _apply_ordering_fields(qs, ordering: str, allowed: set[str]) -> QuerySet:
    """Apply comma-separated ordering fields to a queryset.

    Each field may be prefixed with ``-`` for descending.  Fields not in
    *allowed*, or not actually orderable on the model (e.g. a computed column a
    caller mistakenly listed in ``ordering_fields``), are silently ignored —
    matching the Django/DRF convention and keeping a bad sort from 500-ing.

    This is the low-level helper used by both the HTML list view and the
    REST API layer.
    """
    validated = []
    for part in ordering.split(","):
        field = part.strip().lstrip("-")
        if field in allowed and _field_is_orderable(qs, field):
            validated.append(part.strip())
    if validated:
        return qs.order_by(*validated)
    return qs


def _apply_ordering(qs, request: HttpRequest, crud_config) -> QuerySet:
    """Apply ?ordering= sort to a queryset using list_fields as allowed fields.

    The allowed set is derived from ``ordering_fields`` (if set) or
    ``list_fields``, restricted to real model fields (computed/transform-only
    columns are excluded).
    """
    ordering = request.GET.get("ordering", "").strip()
    if not ordering:
        # Paginating an unordered queryset can repeat or skip rows between
        # pages (Django's UnorderedObjectListWarning) — e.g. the custom User
        # model has no Meta.ordering. Fall back to a stable pk order.
        return qs if qs.ordered else qs.order_by("pk")

    # Build allowed set: ordering_fields override, else list_fields filtered to model fields
    allowed = set(getattr(crud_config, "ordering_fields", None) or [])
    if not allowed:
        model_field_names = {f.name for f in crud_config.model._meta.get_fields()}
        allowed = {f for f in crud_config._get_list_fields() if f in model_field_names}

    return _apply_ordering_fields(qs, ordering, allowed)


def _apply_list_filters(qs, request: HttpRequest, crud_config) -> QuerySet:
    """Apply query-param filters to a queryset using configured filter_fields."""
    from datetime import timedelta

    from django.utils import timezone

    filter_fields = crud_config._resolve_filter_fields()
    if not filter_fields:
        return qs
    for field_name in filter_fields:
        value = request.GET.get(field_name, "").strip()
        if not value:
            continue
        # Per-field override. A CRUDView whose stored column is not the value the
        # rest of the page reasons about (approvals: an overdue row's `status` is
        # still "pending" until a sweep flips it) must be able to make the filter
        # agree with its own stat cards, or the page contradicts itself. (F-29.)
        # getattr, not a direct call: `crud_config` is duck-typed — datasets passes
        # a `_ConfigAdapter` that implements only the list-filter surface.
        _override = getattr(crud_config, "apply_filter", None)
        overridden = _override(qs, field_name, value, request) if _override else NotImplemented
        if overridden is not NotImplemented:
            qs = overridden
            continue
        try:
            model_field = crud_config.model._meta.get_field(field_name)
        except Exception:
            continue
        from django.db import models as _m

        # Boolean fields: accept true/false/1/0
        if isinstance(model_field, _m.BooleanField):
            if value.lower() in ("true", "1", "yes"):
                qs = qs.filter(**{field_name: True})
            elif value.lower() in ("false", "0", "no"):
                qs = qs.filter(**{field_name: False})
            continue

        # Date/DateTime fields: preset filters
        if isinstance(model_field, (_m.DateField, _m.DateTimeField)):
            today = timezone.localdate()
            is_datetime = isinstance(model_field, _m.DateTimeField)
            lookup_prefix = f"{field_name}__date" if is_datetime else field_name
            if value == "today":
                qs = qs.filter(**{lookup_prefix: today})
            elif value == "yesterday":
                qs = qs.filter(**{lookup_prefix: today - timedelta(days=1)})
            elif value == "week":
                qs = qs.filter(**{f"{lookup_prefix}__gte": today - timedelta(days=7)})
            elif value == "month":
                qs = qs.filter(**{f"{lookup_prefix}__month": today.month, f"{lookup_prefix}__year": today.year})
            elif value == "year":
                qs = qs.filter(**{f"{lookup_prefix}__year": today.year})
            continue

        # Text-type fields: use icontains for substring matching
        if isinstance(model_field, (_m.CharField, _m.TextField)):
            meta = _build_filter_meta(crud_config.model, field_name)
            if meta and meta["type"] == "text":
                qs = qs.filter(**{f"{field_name}__icontains": value})
                continue

        qs = qs.filter(**{field_name: value})
    return qs


# Query params that are *not* filters: they change how the same result set is
# paged, ordered or drawn, or they are internal markers. A list that comes back
# empty while only these are present is genuinely empty, not filtered-to-empty,
# so the empty state must offer "create the first one" rather than "clear your
# filters" (see _has_active_filters).
NON_FILTER_QUERY_PARAMS = frozenset(
    {
        "page",
        "page_size",
        "ordering",
        "display",
        "_notification",
        "format",
        "expand",
    }
)


def _has_active_filters(request: HttpRequest, crud_config) -> bool:
    """True when the request narrows the list with a real search or filter.

    Deliberately *not* ``request.GET.urlencode``: that is truthy for pagination,
    ordering, the display toggle and the ``?_notification=`` marker the bell
    click-through appends, none of which narrow anything. The view already knows
    its own ``search_fields``/``filter_fields``, so ask those instead, and treat
    an unknown param as a filter only if it is not on the known-inert list (a
    downstream ``get_list_queryset`` may read its own params).
    """
    if request.GET.get("q", "").strip():
        return True
    filter_fields = set(crud_config._resolve_filter_fields())
    for key, value in request.GET.lists():
        if key in NON_FILTER_QUERY_PARAMS or key == "q":
            continue
        if key in filter_fields and any(v.strip() for v in value):
            return True
        if key not in filter_fields and any(v.strip() for v in value):
            # Unknown, non-inert param — a custom scoper may act on it.
            return True
    return False


def _build_toolbar_context(request: HttpRequest, crud_config) -> dict[str, Any]:
    """Build context dict for the list toolbar template.

    The toolbar shows when search_fields or filter_fields are configured.
    """
    search_fields = crud_config._resolve_search_fields()
    filter_fields = crud_config._resolve_filter_fields()
    if not search_fields and not filter_fields:
        return {"show_toolbar": False, "toolbar_filters": [], "toolbar_has_active_filter": False}

    # Build filter metadata for the template
    filters = []
    for field_name in filter_fields:
        meta = _build_filter_meta(crud_config.model, field_name)
        if meta:
            meta["current_value"] = request.GET.get(field_name, "")
            filters.append(meta)

    has_active_filter = any(f["current_value"] for f in filters)

    # Build a helpful search placeholder
    search_placeholder = "Search..."
    if search_fields:
        field_labels = []
        for f in search_fields[:3]:
            clean = f.replace("__", " ").replace("_", " ")
            field_labels.append(clean)
        search_placeholder = f"Search {', '.join(field_labels)}..."

    return {
        "show_toolbar": True,
        "toolbar_search_fields": search_fields,
        "toolbar_search_query": request.GET.get("q", ""),
        "toolbar_search_placeholder": search_placeholder,
        "toolbar_filters": filters,
        "toolbar_has_active_filter": has_active_filter,
    }


def _build_filter_meta(model, field_name: str) -> dict[str, Any] | None:
    """Build filter widget metadata for a single field."""
    from django.db import models as _m

    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return None

    meta: dict[str, Any] = {
        "name": field_name,
        "label": str(getattr(field, "verbose_name", field_name)).capitalize(),
    }

    # Date/DateTime fields → preset dropdown
    if isinstance(field, (_m.DateField, _m.DateTimeField)):
        meta["type"] = "choice"
        meta["is_date"] = True
        meta["choices"] = [
            ("", "All"),
            ("today", "Today"),
            ("yesterday", "Yesterday"),
            ("week", "Past 7 days"),
            ("month", "This month"),
            ("year", "This year"),
        ]
        return meta

    # Boolean fields → toggle (All / Yes / No)
    if isinstance(field, (_m.BooleanField,)):
        meta["type"] = "boolean"
        meta["choices"] = [("", "All"), ("true", "Yes"), ("false", "No")]
        return meta

    # Choice fields → dropdown
    if field.choices:
        choices = [("", "All")]
        for val, label in field.flatchoices:
            choices.append((str(val), str(label)))
        meta["type"] = "choice"
        meta["choices"] = choices
        return meta

    # ForeignKey → dropdown of related objects (capped at 100)
    if isinstance(field, _m.ForeignKey):
        related_model = field.related_model
        try:
            objects = related_model._default_manager.all()[:100]
            choices = [("", "All")]
            for obj in objects:
                choices.append((str(obj.pk), str(obj)))
            meta["type"] = "choice"
            meta["choices"] = choices
            return meta
        except Exception:
            return None

    # Integer/text fields with limited distinct values → dropdown
    try:
        distinct_count = model.objects.values(field_name).distinct().count()
        if distinct_count <= 30:
            values = model.objects.values_list(field_name, flat=True).distinct().order_by(field_name)[:30]
            choices = [("", "All")]
            for val in values:
                if val is not None:
                    display = str(val)
                    # Use get_FOO_display style if available
                    choices.append((str(val), display))
            meta["type"] = "choice"
            meta["choices"] = choices
            return meta
    except Exception:
        pass

    # Fallback: text input filter
    meta["type"] = "text"
    return meta


class _CRUDContextMixin:
    """Injects CRUD metadata into template context for all generated views."""

    crud_config: type["CRUDView"]  # injected by CRUDView._make_view() on every generated view

    # Reserved context variable names that Django's auth/template system uses.
    # If the model's default context_object_name would collide, we prefix it.
    _RESERVED_CONTEXT_NAMES = {"user", "request", "messages", "perms"}

    def get_context_object_name(self, obj):
        name = super().get_context_object_name(obj)
        if name in self._RESERVED_CONTEXT_NAMES:
            return f"crud_{name}"
        return name

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cfg = self.crud_config
        url_base = cfg._get_url_base()
        meta = cfg.model._meta
        context.update(
            {
                "crud_config": cfg,
                "object_verbose_name": str(meta.verbose_name).capitalize(),
                "object_verbose_name_plural": str(meta.verbose_name_plural).capitalize(),
                "url_base": url_base,
                "url_namespace": cfg.namespace,
                "list_fields": cfg._get_list_columns(),
                "detail_fields": cfg._get_detail_fields(),
                "link_field": cfg._get_link_field(),
                "crud_actions": cfg.actions,
                "field_transforms": cfg._get_effective_transforms(),
                # Legacy keys for backward compat with custom templates
                "field_formatters": cfg.field_formatters,
                "preview_fields": cfg.preview_fields,
                # Bulk operations
                "enable_bulk": bool(cfg.bulk_actions),
                "bulk_actions": [a.value for a in cfg.bulk_actions],
                "bulk_url": cfg._reverse(f"{url_base}-bulk") if cfg.bulk_actions else "",
            }
        )
        # Optional parent breadcrumb: (label, url_name) tuple
        if cfg.breadcrumb_parent:
            label, url_name = cfg.breadcrumb_parent
            context["breadcrumb_parent_label"] = label
            context["breadcrumb_parent_url_name"] = url_name
        if Action.CREATE in cfg.actions:
            context["create_view_url"] = cfg._reverse(f"{url_base}-create")
        if Action.LIST in cfg.actions:
            context["list_view_url"] = cfg._reverse(f"{url_base}-list")
            list_name = f"{url_base}-list"
            if cfg.namespace:
                list_name = f"{cfg.namespace}:{list_name}"
            context["list_view_url_name"] = list_name
        return context


class _CRUDObjectPermissionMixin:
    """Routes every generated single-object fetch through ``check_object_permission``.

    Mixed into all five single-object bases (detail, update, delete, field
    preview, related tab). Without it, a CRUDView that expresses ownership by
    overriding one base's ``get_object`` protects exactly that base — the
    related-tab and field-preview routes stay wide open, which is a live
    cross-user disclosure on any view that opts out of ``get_detail_queryset``.
    """

    crud_config: type["CRUDView"]

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)  # type: ignore[misc]
        self.crud_config.check_object_permission(obj, self.request)  # type: ignore[attr-defined]
        return obj


class _CRUDListBase(_CRUDContextMixin, ListView):
    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            htmx_target = self.request.headers.get("HX-Target", "")
            # Toolbar search/filter: return the list content partial
            if htmx_target == "crud-list-content":
                return self.crud_config._get_template_names("list_content")
            # Display area swap (pagination, display switch): return just the display template
            display = self._get_active_display()
            if display and (self.request.GET.get("display") or htmx_target == "crud-display-area"):
                return [display.template_name]
            return self.crud_config._get_template_names("list_partial")
        return self.crud_config._get_template_names("list")

    def get_queryset(self):
        qs = self.crud_config._get_queryset()
        qs = self.crud_config.get_list_queryset(qs, self.request)
        qs = _apply_list_search(qs, self.request, self.crud_config)
        qs = _apply_list_filters(qs, self.request, self.crud_config)
        qs = _apply_ordering(qs, self.request, self.crud_config)
        return qs

    def _get_active_display(self):
        """Determine the active display for this request."""
        cfg = self.crud_config
        displays = cfg._get_displays()
        if not displays:
            return None

        # Check ?display= query param
        requested = self.request.GET.get("display", "")
        if requested:
            for d in displays:
                if d.name == requested:
                    return d

        # Default display
        if cfg.default_display:
            d = cfg.default_display
            return d() if isinstance(d, type) else d
        return displays[0]

    def get_context_data(self, **kwargs):
        from .displays import build_palette_context

        context = super().get_context_data(**kwargs)
        cfg = self.crud_config

        # Toolbar context (search + filters)
        context.update(_build_toolbar_context(self.request, cfg))

        # Empty-state branch selector. The empty state is lower-cased mid-sentence
        # and says what to do next: an empty list *after a search* means "widen
        # it", not "there is nothing here".
        context["has_active_filters"] = _has_active_filters(self.request, cfg)

        # Total count for toolbar (before pagination, after search/filter)
        qs = self.get_queryset()
        context["toolbar_total_count"] = qs.count()

        # List accessories — pass UNFILTERED queryset so stats reflect totals
        if cfg.list_accessories:
            full_qs = cfg._get_queryset()
            full_qs = cfg.get_list_queryset(full_qs, self.request)
            rendered = []
            for accessory in cfg.list_accessories:
                rendered.append(accessory.render(full_qs, cfg, self.request))
            context["list_accessories_html"] = rendered

        # Try display protocol first (when displays are configured)
        display = self._get_active_display()
        if display:
            display_ctx = display.get_context(qs, cfg, self.request)
            context.update(display_ctx)
            context["display_template"] = display.template_name
            context["active_display"] = display.name
            all_displays = cfg._get_displays()
            context["display_palette"] = build_palette_context(all_displays, display, self.request)
            if len(all_displays) > 1:
                context["available_displays"] = all_displays
            # Per-display bulk opt-out: displays can set supports_bulk=False
            if not getattr(display, "supports_bulk", True):
                context["enable_bulk"] = False
        else:
            # Legacy basic table path — attach the shared pagination helpers.
            page_obj = context.get("page_obj")
            if page_obj:
                from .pagination import attach_display_helpers

                attach_display_helpers(page_obj)
        return context


class _CRUDDetailBase(_CRUDObjectPermissionMixin, _CRUDContextMixin, DetailView):
    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            display = self._get_active_detail_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
        return self.crud_config._get_template_names("detail")

    def get_queryset(self):
        # Scoped like the list (get_detail_queryset defaults to get_list_queryset)
        # so a row hidden from the list isn't readable at its own URL.
        return self.crud_config.get_detail_queryset(
            self.crud_config._get_queryset(), self.request
        )

    def _get_active_detail_display(self):
        """Determine the active detail display for this request."""
        cfg = self.crud_config
        displays = cfg._get_detail_displays()
        if not displays:
            return None

        requested = self.request.GET.get("display", "")
        if requested:
            for d in displays:
                if d.name == requested:
                    return d

        if cfg.default_display:
            d = cfg.default_display
            return d() if isinstance(d, type) else d
        return displays[0]

    def get_context_data(self, **kwargs):
        from .displays import build_palette_context

        context = super().get_context_data(**kwargs)
        cfg = self.crud_config

        display = self._get_active_detail_display()
        if display:
            display_ctx = display.get_context(self.object, cfg, self.request)
            context.update(display_ctx)
            context["display_template"] = display.template_name
            context["active_display"] = display.name
            all_displays = cfg._get_detail_displays()
            context["display_palette"] = build_palette_context(all_displays, display, self.request)
            if len(all_displays) > 1:
                context["available_displays"] = all_displays

        # Related tabs: enrich _get_related_tabs() with live counts and URLs
        tabs = cfg._get_related_tabs()
        if tabs:
            url_base = cfg._get_url_base()
            related_tabs = []
            for tab in tabs:
                accessor = tab["accessor"]
                related_crud = tab["related_crud"]
                related_url_base = related_crud._get_url_base()
                enriched = {
                    # Identity
                    "accessor": accessor,
                    "field_name": tab["field_name"],
                    # Display
                    "verbose_name": tab["verbose_name"],
                    "verbose_name_singular": str(tab["related_model"]._meta.verbose_name).capitalize(),
                    "count": getattr(self.object, accessor).count(),
                    # Related model info (for custom templates)
                    "related_model_name": tab["related_model"]._meta.model_name,
                    "related_app_label": tab["related_model"]._meta.app_label,
                    "related_url_base": related_url_base,
                    "related_list_url": related_crud._reverse(f"{related_url_base}-list"),
                    # Tab content URL (HTMX or full-page)
                    "content_url": cfg._reverse(
                        f"{url_base}-related-tab",
                        kwargs={"pk": self.object.pk, "accessor": accessor},
                    ),
                }
                related_tabs.append(enriched)
            context["related_tabs"] = related_tabs

        return context


class _CRUDFormDisplayMixin:
    """Shared display protocol logic for create and update views."""

    _form_action = "form"  # Override in subclass: "create" or "edit"

    def _get_active_form_display(self):
        """Determine the active form display for this request."""
        cfg = self.crud_config
        displays = cfg._get_form_displays(self._form_action)
        if not displays:
            return None

        requested = self.request.GET.get("display", "")
        if requested:
            for d in displays:
                if d.name == requested:
                    return d

        if cfg.default_form_display:
            d = cfg.default_form_display
            return d() if isinstance(d, type) else d
        return displays[0]

    def _inject_display_context(self, context, obj=None):
        """Add display protocol context if form displays are configured."""
        from .displays import build_palette_context

        display = self._get_active_form_display()
        if display:
            display_ctx = display.get_context(context.get("form"), obj, self.crud_config, self.request)
            context.update(display_ctx)
            context["display_template"] = display.template_name
            context["active_display"] = display.name
            all_displays = self.crud_config._get_form_displays(self._form_action)
            context["display_palette"] = build_palette_context(all_displays, display, self.request)
            if len(all_displays) > 1:
                context["available_displays"] = all_displays
        return context


class _CRUDCreateBase(_CRUDFormDisplayMixin, _CRUDContextMixin, CreateView):
    _form_action = "create"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            display = self._get_active_form_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
        return self.crud_config._get_template_names("create")

    def get_form_class(self):
        return self.crud_config.form_class or self.crud_config._make_form_class()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return self._inject_display_context(context, obj=None)

    def form_valid(self, form):
        # The documented `on_form_valid` hook fired from REST, MCP and bulk
        # update but NOT from the primary (web) path, so every CRUDView using it
        # to stamp an owner / denormalise / file an approval had a data-integrity
        # hole reachable from the UI. (F-05.)
        response = super().form_valid(form)
        self.crud_config.on_form_valid(self.request, form, self.object, is_create=True)
        return response

    def get_success_url(self):
        return self.crud_config._reverse(f"{self.crud_config._get_url_base()}-list")


class _CRUDUpdateBase(_CRUDObjectPermissionMixin, _CRUDFormDisplayMixin, _CRUDContextMixin, UpdateView):
    _form_action = "edit"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            display = self._get_active_form_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
        return self.crud_config._get_template_names("edit")

    def get_queryset(self):
        return self.crud_config.get_detail_queryset(
            self.crud_config._get_queryset(), self.request
        )

    def get_form_class(self):
        return self.crud_config.form_class or self.crud_config._make_form_class()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return self._inject_display_context(context, obj=self.object)

    def form_valid(self, form):
        # See _CRUDCreateBase.form_valid — same gap on the edit path. (F-05.)
        response = super().form_valid(form)
        self.crud_config.on_form_valid(self.request, form, self.object, is_create=False)
        return response

    def get_success_url(self):
        # Redirect to the detail page when the view exposes DETAIL; otherwise
        # fall back to the list (a DETAIL-less CRUDView has no `-detail` route,
        # so reversing it would 500 after a successful save).
        cfg = self.crud_config
        base = cfg._get_url_base()
        if Action.DETAIL in cfg.actions:
            return cfg._reverse(f"{base}-detail", kwargs={"pk": self.object.pk})
        return cfg._reverse(f"{base}-list")


class _CRUDDeleteBase(_CRUDObjectPermissionMixin, _CRUDContextMixin, DeleteView):
    def get_template_names(self):
        return self.crud_config._get_template_names("confirm_delete")

    def get_queryset(self):
        return self.crud_config.get_detail_queryset(
            self.crud_config._get_queryset(), self.request
        )

    def get_success_url(self):
        return self.crud_config._reverse(f"{self.crud_config._get_url_base()}-list")

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except (ProtectedError, RestrictedError) as e:
            protected = getattr(e, "protected_objects", None) or getattr(e, "restricted_objects", set())
            model_name = type(next(iter(protected))).__name__ if protected else "other records"
            count = len(protected)
            msg = f"Cannot delete — {count} {model_name} record{'s' if count != 1 else ''} still linked."
        except IntegrityError:
            msg = "Cannot delete — a database constraint prevented this action."
        except Exception:
            logger.exception("Delete of %s pk=%s failed", self.crud_config.model.__name__, kwargs.get("pk"))
            msg = "Delete failed — an unexpected error occurred."
        else:
            return  # unreachable, but keeps linters happy
        if getattr(request, "htmx", False) or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return HttpResponse(msg, status=409)
        messages.error(request, msg)
        return _redirect(self.get_success_url())


def _log_bulk_action(request, verb: str, model: type[Model], ok_ids: list, errors: dict, *, fields=None) -> None:
    """One structured log line per bulk action — the log-viewer-visibility half of the fix.

    Deliberately ONE line, not one per row: a bulk delete/update can touch
    thousands of rows, and a `LogRecord` per row would be the "unbounded
    growth under load" failure mode `DatabaseLogHandler` itself exists to
    avoid (see its module docstring). The row count and error count are
    always exact in the message text; the row IDs in `extra` are capped
    (`_BULK_LOG_ID_CAP`) so one huge bulk action can't blow up a single log
    line/row — this is a "was there activity, and roughly what" record, not a
    substitute for the per-object audit trail `_audit_bulk_action` writes.
    """
    actor = request.user.get_username() if getattr(request.user, "is_authenticated", False) else "anonymous"
    extra = {"ids": ok_ids[:_BULK_LOG_ID_CAP], "errors": errors}
    if fields is not None:
        extra["fields"] = fields
    # Deletes log at WARNING so they reach the DB log handler at its default
    # WARNING baseline — at INFO the "visible in the log viewer" half of the
    # v0.20.0 fix never persisted. Updates stay INFO. (Audit 2026-09-13, D8.)
    logger.log(
        logging.WARNING if verb == "delete" else logging.INFO,
        "Bulk %s: %s %s %d/%d %s row(s), %d error(s)",
        verb,
        actor,
        "deleted" if verb == "delete" else "updated",
        len(ok_ids),
        len(ok_ids) + len(errors),
        model.__name__,
        len(errors),
        extra=extra,
    )


def _audit_bulk_action(
    request, model: type[Model], snapshots: list[tuple[Any, str]], action_flag: int, message: str
) -> None:
    """Per-object audit trail entries for a bulk action, written in one query.

    Takes ``(pk, repr)`` snapshots rather than live model instances — for
    delete specifically, ``obj.pk`` is set to ``None`` by Django the moment
    ``obj.delete()`` succeeds, so building the entries from the
    already-deleted instances afterward (as Django admin's own
    ``LogEntry.objects.log_actions()`` batch helper does, by reading
    ``obj.pk`` itself) would silently write every row with ``object_id=None``.
    Capturing ``(pk, str(obj))`` *before* deleting sidesteps that; using the
    same snapshot shape for bulk update too (where the object survives) keeps
    one code path for both instead of two.

    Still one ``bulk_create`` query for however many rows were touched — the
    same "who touched exactly which record" answerability a single-object
    write gets via `AuditMixin`, without paying N queries for it. Best-effort
    and silent on failure — audit logging must never be why a bulk action
    itself fails — and skipped entirely for an unauthenticated actor, since
    `LogEntry.user` is required.
    """
    if not snapshots or getattr(request.user, "pk", None) is None:
        return
    try:
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(model)
        entries = [
            LogEntry(
                user_id=request.user.pk,
                content_type_id=ct.pk,
                object_id=str(pk),
                object_repr=repr_str,
                action_flag=action_flag,
                change_message=message,
            )
            for pk, repr_str in snapshots
        ]
        LogEntry.objects.bulk_create(entries)
    except Exception:
        logger.exception("Bulk action audit trail write failed for %s", model.__name__)


class _CRUDBulkActionView:
    """Handles bulk delete and bulk update operations via POST.

    Processes objects individually to respect per-object permission hooks
    and catch ProtectedError per row.
    """

    crud_config: type["CRUDView"]  # injected by CRUDView._make_bulk_action_view()

    @classmethod
    def as_view(cls):
        from django.views import View

        config = cls.crud_config

        class BulkView(View):
            def post(self, request, *args, **kwargs):
                import json as _json

                # Parse request body (JSON or form data)
                content_type = request.content_type or ""
                if "json" in content_type:
                    try:
                        body = _json.loads(request.body)
                    except (ValueError, _json.JSONDecodeError):
                        return HttpResponse(
                            _json.dumps({"error": "Invalid JSON"}),
                            status=400,
                            content_type="application/json",
                        )
                    action = body.get("action", "")
                    ids = body.get("ids", [])
                    fields_data = body.get("fields", {})
                else:
                    action = request.POST.get("action", "")
                    ids = request.POST.getlist("ids[]") or request.POST.getlist("ids")
                    fields_data = {}

                # Validate IDs
                try:
                    ids = config._coerce_pks(ids)  # pk-type aware, not int-only (F-38)
                except (ValueError, TypeError, DjangoValidationError):
                    return HttpResponse(
                        _json.dumps({"error": "Invalid IDs"}),
                        status=400,
                        content_type="application/json",
                    )

                if not ids:
                    return HttpResponse(
                        _json.dumps({"error": "No IDs provided"}),
                        status=400,
                        content_type="application/json",
                    )

                if action == "delete":
                    return self._bulk_delete(request, ids, config)
                elif action == "update":
                    return self._bulk_update(request, ids, fields_data, config)
                else:
                    return HttpResponse(
                        _json.dumps({"error": f"Unknown action: {action}"}),
                        status=400,
                        content_type="application/json",
                    )

            def _bulk_delete(self, request, ids, cfg):
                import json as _json

                if BulkAction.DELETE not in cfg.bulk_actions:
                    return HttpResponse(
                        _json.dumps({"error": "Bulk delete not enabled"}),
                        status=403,
                        content_type="application/json",
                    )

                qs = cfg.get_detail_queryset(cfg._get_queryset(), request).filter(pk__in=ids)
                objects = {obj.pk: obj for obj in qs}
                deleted_ids = []
                deleted_snapshots = []  # (pk, repr) captured before delete() clears obj.pk
                errors = {}

                for pk in ids:
                    obj = objects.get(pk)
                    if obj is None:
                        errors[str(pk)] = "Not found"
                        continue
                    if not cfg.can_delete(obj, request):
                        errors[str(pk)] = "Permission denied"
                        continue
                    # The per-object hook must run here too: a bulk action is a
                    # write to N single objects, and a view that expresses
                    # ownership in check_object_permission (rather than in
                    # get_detail_queryset) would otherwise have it bypassed by
                    # the least-travelled route. That is F-27 exactly. (F-50.)
                    try:
                        cfg.check_object_permission(obj, request)
                    except (PermissionDenied, Http404):
                        errors[str(pk)] = "Permission denied"
                        continue
                    try:
                        # Captured before delete(): Django sets obj.pk to None
                        # the moment the delete succeeds, so this must not be
                        # read back off the object afterward.
                        object_repr = str(obj)[:200]
                        obj.delete()
                        deleted_ids.append(pk)
                        deleted_snapshots.append((pk, object_repr))
                    except (ProtectedError, RestrictedError) as e:
                        protected = getattr(e, "protected_objects", None) or getattr(e, "restricted_objects", set())
                        name = type(next(iter(protected))).__name__ if protected else "other records"
                        cnt = len(protected)
                        s = "s" if cnt != 1 else ""
                        errors[str(pk)] = f"Cannot delete — {cnt} {name} record{s} still linked."
                    except IntegrityError:
                        errors[str(pk)] = "Cannot delete — a database constraint prevented this action."
                    except Exception:
                        logger.exception("Bulk delete of %s pk=%s failed", cfg.model.__name__, pk)
                        errors[str(pk)] = "Delete failed — an unexpected error occurred."

                msg = f"Deleted {len(deleted_ids)} of {len(ids)}"
                _log_bulk_action(request, "delete", cfg.model, deleted_ids, errors)
                _audit_bulk_action(request, cfg.model, deleted_snapshots, DELETION, "Bulk delete via CRUDView")

                return HttpResponse(
                    _json.dumps({"deleted": deleted_ids, "errors": errors, "message": msg}),
                    content_type="application/json",
                )

            def _bulk_update(self, request, ids, fields_data, cfg):
                import json as _json

                if BulkAction.UPDATE not in cfg.bulk_actions:
                    return HttpResponse(
                        _json.dumps({"error": "Bulk update not enabled"}),
                        status=403,
                        content_type="application/json",
                    )

                if not fields_data:
                    return HttpResponse(
                        _json.dumps({"error": "No fields provided"}),
                        status=400,
                        content_type="application/json",
                    )

                # Validate field names
                allowed = set(cfg.can_bulk_update_fields())
                invalid = set(fields_data.keys()) - allowed
                if invalid:
                    return HttpResponse(
                        _json.dumps({"error": f"Fields not allowed for bulk update: {', '.join(sorted(invalid))}"}),
                        status=400,
                        content_type="application/json",
                    )

                qs = cfg.get_detail_queryset(cfg._get_queryset(), request).filter(pk__in=ids)
                objects = {obj.pk: obj for obj in qs}
                updated = []
                updated_snapshots = []  # (pk, repr) captured just after form.save()
                errors = {}

                for pk in ids:
                    obj = objects.get(pk)
                    if obj is None:
                        errors[str(pk)] = "Not found"
                        continue
                    if not cfg.can_update(obj, request):
                        errors[str(pk)] = "Permission denied"
                        continue
                    try:
                        cfg.check_object_permission(obj, request)  # see _bulk_delete (F-50)
                    except (PermissionDenied, Http404):
                        errors[str(pk)] = "Permission denied"
                        continue

                    # Build PATCH-style form: merge existing values with new fields
                    from .form_bridge import merge_form_payload

                    form_class = cfg.form_class or cfg._make_form_class()
                    merged = merge_form_payload(
                        form_class,
                        fields_data,
                        instance=obj,
                        instance_fields=cfg.fields or [],
                    )
                    form = form_class(merged, instance=obj)
                    if form.is_valid():
                        obj = form.save()
                        cfg.on_form_valid(request, form, obj, is_create=False)
                        updated.append(pk)
                        updated_snapshots.append((obj.pk, str(obj)[:200]))
                    else:
                        errors[str(pk)] = {k: [str(e) for e in v] for k, v in form.errors.items()}

                total = len(ids)
                updated_count = len(updated)
                msg = f"Updated {updated_count} of {total}"
                _log_bulk_action(request, "update", cfg.model, updated, errors, fields=sorted(fields_data))
                _audit_bulk_action(
                    request,
                    cfg.model,
                    updated_snapshots,
                    CHANGE,
                    f"Bulk update via CRUDView (fields: {', '.join(sorted(fields_data))})",
                )

                return HttpResponse(
                    _json.dumps({"updated": updated, "errors": errors, "message": msg}),
                    content_type="application/json",
                )

        # Apply mixins
        bases = tuple(config._resolved_mixins()) + (BulkView,)
        view_cls = type(f"{config.model.__name__}BulkActionView", bases, {})
        return view_cls.as_view()


def _make_bulk_update_form_view(crud_config):
    """Create a view that returns HTML for the bulk update field picker."""
    from django.views import View

    config = crud_config

    class BulkUpdateFormView(View):
        def get(self, request, *args, **kwargs):
            from django.utils.html import escape

            allowed_fields = config.can_bulk_update_fields()
            form_class = config.form_class or config._make_form_class()
            form = form_class()

            html_parts = []
            for field_name in allowed_fields:
                if field_name not in form.fields:
                    continue
                field = form.fields[field_name]
                label = field.label or field_name.replace("_", " ").capitalize()
                attrs = {
                    "id": f"id_bulk_{field_name}",
                    "class": "vTextField",
                    "style": "width: 100%;",
                }
                widget_html = field.widget.render(
                    f"bulk_{field_name}",
                    None,
                    attrs=attrs,
                )

                esc_name = escape(field_name)
                esc_label = escape(label)
                html_parts.append(
                    '<div class="bulk-field-row">'
                    '<label class="bulk-field-label">'
                    f'<input type="checkbox" class="bulk-field-toggle"'
                    f' data-field="{esc_name}">'
                    f" {esc_label}"
                    "</label>"
                    '<div class="bulk-field-widget"'
                    ' style="display: none; margin-top: 0.5rem;">'
                    f"{widget_html}"
                    "</div>"
                    "</div>"
                )

            html_parts.append(
                "<script>"
                'document.querySelectorAll("#bulk-update-fields .bulk-field-toggle").forEach(function(cb) {'
                '  cb.addEventListener("change", function() {'
                '    var widget = this.closest("div").querySelector(".bulk-field-widget");'
                '    widget.style.display = this.checked ? "block" : "none";'
                "  });"
                "});"
                "</script>"
            )

            return HttpResponse("".join(html_parts))

    # Apply mixins
    bases = tuple(config._resolved_mixins()) + (BulkUpdateFormView,)
    view_cls = type(f"{config.model.__name__}BulkUpdateFormView", bases, {})
    return view_cls.as_view()


class _CRUDFieldPreviewBase(_CRUDObjectPermissionMixin, _CRUDContextMixin, DetailView):
    """Server-rendered field preview partial, loaded via HTMX."""

    def get_queryset(self):
        return self.crud_config.get_detail_queryset(
            self.crud_config._get_queryset(), self.request
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        field_name = self.kwargs["field_name"]

        # Security: only allow fields whose transform has has_expanded=True
        effective = self.crud_config._get_effective_transforms()
        spec = effective.get(field_name)
        transform, options = _resolve_transform_spec(spec) if spec else (None, {})

        if not transform or not getattr(transform, "has_expanded", False):
            raise Http404

        raw_value = getattr(self.object, field_name, "")
        expanded_ctx = transform.expanded(raw_value, self.object, field_name, ctx, **options)

        ctx["field_name"] = field_name
        ctx.update(expanded_ctx)
        return ctx

    def get_template_names(self):
        field_name = self.kwargs.get("field_name", "")
        effective = self.crud_config._get_effective_transforms()
        spec = effective.get(field_name)
        transform, _ = _resolve_transform_spec(spec) if spec else (None, {})

        if transform and hasattr(transform, "get_expanded_template"):
            custom = transform.get_expanded_template()
            if custom:
                return [custom]

        return self.crud_config._get_template_names("field_preview")


class _CRUDRelatedTabBase(_CRUDObjectPermissionMixin, _CRUDContextMixin, DetailView):
    """HTMX partial: renders a paginated table of related objects for one tab."""

    def get_queryset(self) -> Any:
        return self.crud_config.get_detail_queryset(
            self.crud_config._get_queryset(), self.request
        )

    def get_template_names(self) -> list[str]:
        """Instance → app → default chain, like every sibling view.

        This alone hardcoded its template, so a project could override every
        other CRUD surface per model but not the related-tab partial — an
        inconsistency rather than a decision (`_CRUDFieldPreviewBase`, directly
        above, resolves the same way).

        The shipped partial lives at ``crud/includes/related_tab_content.html``,
        which does not fit ``_get_template_names``'s ``crud/object_{suffix}``
        default, so it is appended as the final fallback instead of being moved:
        the loader takes the first template that exists, so behavior is
        unchanged when no override is present.
        """
        return [
            *self.crud_config._get_template_names("related_tab"),
            "smallstack/crud/includes/related_tab_content.html",
        ]

    def get(self, request, *args, **kwargs) -> HttpResponse:
        self.object = self.get_object()
        accessor = self.kwargs["accessor"]

        # Validate accessor against allowed tabs
        cfg = self.crud_config
        tabs = cfg._get_related_tabs()
        tab = None
        for t in tabs:
            if t["accessor"] == accessor:
                tab = t
                break
        if tab is None:
            raise Http404

        # Get related queryset
        related_qs = getattr(self.object, accessor).all()

        # Related model's CRUDView for field/link config
        related_crud = tab["related_crud"]
        list_fields = list(related_crud._get_list_columns())
        link_field = related_crud._get_link_field()
        url_base = related_crud._get_url_base()

        # Remove FK field pointing back to parent (redundant in context)
        fk_field = tab["field_name"]
        if fk_field and fk_field in list_fields:
            list_fields.remove(fk_field)
            if link_field == fk_field:
                link_field = list_fields[0] if list_fields else None

        # Paginate
        from .pagination import paginate_queryset

        page_obj = paginate_queryset(
            related_qs, request, page_size=cfg.related_tabs_paginate_by
        )

        # Row-link intent for {% crud_table %}, and ONLY that: exactly one action
        # is forwarded, so a related tab renders clickable rows without growing
        # an Edit/Delete action column.
        #
        # This was hardcoded to [Action.DETAIL], so crud_table reversed
        # "<url_base>-detail" for views whose `actions` omit DETAIL — those routes
        # are never generated (see get_urls), giving NoReverseMatch → 500. Because
        # the tab loads lazily over HTMX, that surfaced as a tab with a count badge
        # and an empty body rather than a visible error.
        #
        # Preferring DETAIL then UPDATE matches crud_table's own documented
        # fallback ("no DETAIL ⇒ link the row to the edit view"); with neither, rows
        # render unlinked rather than erroring. Slicing to one keeps a tab whose
        # target routes BOTH from gaining an Edit column it never had. DELETE is
        # never forwarded — a related tab must not become a destructive surface.
        related_actions = list(getattr(related_crud, "actions", None) or [])
        tab_actions = [a for a in (Action.DETAIL, Action.UPDATE) if a in related_actions][:1]

        related_model = tab["related_model"]
        content_url = cfg._reverse(
            f"{cfg._get_url_base()}-related-tab",
            kwargs={"pk": self.object.pk, "accessor": accessor},
        )

        context = self.get_context_data(object=self.object)
        context.update(
            {
                # Table rendering (consumed by {% crud_table %})
                "object_list": page_obj.object_list,
                "page_obj": page_obj,
                "list_fields": list_fields,
                "link_field": link_field,
                "url_base": url_base,
                "url_namespace": related_crud.namespace,
                "crud_actions": tab_actions,
                # The rows in this tab belong to the RELATED model, so the table
                # must be rendered through the related view's config. _CRUDContextMixin
                # seeded this with the PARENT's config, and {% crud_table %} reads
                # row_link_url(), row_actions() and column_widths off it — so parent
                # hooks were applied to child rows, silently pointing a row at an
                # unrelated record that merely shared its pk.
                "crud_config": related_crud,
                "field_transforms": related_crud._get_effective_transforms(),
                "enable_bulk": False,
                # Related tab metadata (for custom templates)
                "related_tab_accessor": accessor,
                "related_tab_field_name": fk_field,
                "related_tab_verbose_name": str(related_model._meta.verbose_name_plural).capitalize(),
                "related_tab_verbose_name_singular": str(related_model._meta.verbose_name).capitalize(),
                "related_tab_model_name": related_model._meta.model_name,
                "related_tab_app_label": related_model._meta.app_label,
                "related_tab_content_url": content_url,
                "related_tab_list_url": related_crud._reverse(f"{url_base}-list"),
                "related_tab_total_count": page_obj.paginator.count,
            }
        )
        return self.render_to_response(context)


# ---------------------------------------------------------------------------
# Transform spec resolution
# ---------------------------------------------------------------------------


def _resolve_transform_spec(spec) -> tuple[Any, dict]:
    """Resolve a field_transforms value to (transform_or_callable, options_dict).

    Spec formats:
        "preview"                → (PreviewTransform instance, {})
        ("badge", {"colors":…})  → (BadgeTransform instance, {"colors":…})
        callable                 → (callable, {})
    """
    if callable(spec) and not isinstance(spec, str):
        return spec, {}
    if isinstance(spec, str):
        transform = _transforms.get(spec)
        return transform, {}
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        name, options = spec
        transform = _transforms.get(name)
        return transform, options if isinstance(options, dict) else {}
    return None, {}


# ---------------------------------------------------------------------------
# CRUDView configuration class
# ---------------------------------------------------------------------------


class CRUDView:
    """Configuration class that generates CRUD views and URL patterns.

    Config source:
        admin_class:      ModelAdmin subclass for config (list_display, search_fields, etc.)
                          When set, CRUDView reads field/layout config from it.
                          When not set, falls back to explicit class attributes (backward compat).

    Model/data:
        model:            Django model class (required)
        fields:           Form fields for create/update (required unless admin_class provides them)
        list_fields:      Columns shown in list table (defaults to admin_class.list_display or fields)
        detail_fields:    Fields shown in detail view (defaults to fields)
        link_field:       Which column links to detail (defaults to first list_field)

    View/routing (not from ModelAdmin):
        url_base:         URL prefix, e.g. "manage/users" (defaults to model_name)
        paginate_by:      Items per page (defaults to admin_class.list_per_page or None)
        mixins:           Auth mixins applied to all generated views
        actions:          Which CRUD actions to generate (default: all 5)
        breadcrumb_parent: Optional (label, url_name) for parent breadcrumb

    Display:
        displays:         Available display classes (empty = legacy auto-detect)
        default_display:  Initial display (defaults to first in displays)
        detail_displays:  Display classes for detail view

    Legacy:
        form_class:       Custom ModelForm (auto-generated if None)
        queryset:         Custom queryset (model.objects.all() if None)
        field_formatters: Deprecated — use field_transforms
        preview_fields:   Deprecated — use field_transforms
        field_transforms: {field_name: "transform_name" | ("name", {opts}) | callable}
    """

    # Model→CRUDView registry: populated eagerly via __init_subclass__ so
    # apps.mcp.AppConfig.ready() can iterate before URL config runs.
    # get_urls() still tops it up — that path remains for legacy compatibility.
    #
    # First-wins (setdefault) on both write paths: the user's CRUDView is
    # defined when its module is imported by Django's app loader. Any
    # CRUDView subclass defined later — notably the Explorer<Model>CRUDView
    # classes apps.explorer dynamically synthesises in its AppConfig.ready()
    # — must not overwrite it. Overwriting silently displaces the user's
    # class from any code that walks _registry at runtime (mcp_doctor's
    # orphan detector, related-tabs URL resolution, etc.), pointing them at
    # Explorer's clone instead.
    _registry: dict[type[Model], type["CRUDView"]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        model = getattr(cls, "model", None)
        if model is not None:
            CRUDView._registry.setdefault(model, cls)

    # Config source
    admin_class: Any = None  # ModelAdmin subclass — the standard Django config DSL

    # Model/data. These are `None`-defaulted config slots that subclasses
    # override with concrete values; the explicit Optional annotations let the
    # type checker accept those overrides (a bare `= None` infers type `None`).
    model: type[Any] | None = None
    fields: list[str] | None = None
    list_fields: list[str] | None = None
    # UI-only override: narrower column set for list template. API/CSV still use list_fields.
    list_columns: list[str] | None = None
    detail_fields: list[str] | None = None
    link_field: str | None = None

    # View/routing
    url_base: str | None = None
    namespace: str | None = None  # URL namespace for child ExplorerSite instances
    paginate_by = 25
    # Auth mixins wrapped around every generated view (HTML + REST). SECURE BY
    # DEFAULT: leave `mixins` unset (None) and the framework applies
    # LoginRequiredMixin. Set it explicitly to override entirely
    # (e.g. [StaffRequiredMixin], or [] for a fully public view). To make a view
    # anonymous, prefer the readable `public = True` flag below. Resolved via
    # `_resolved_mixins()`.
    mixins: list[Any] | None = None
    public = False  # opt into anonymous access (only when `mixins` is unset)
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    breadcrumb_parent: Any = None  # Optional (label, url_name) for parent breadcrumb

    # Display
    displays: list[Any] = []  # List of ListDisplay classes/instances. Empty = legacy auto-detect.
    default_display: Any = None  # Defaults to first in displays
    detail_displays: list[Any] = []  # List of DetailDisplay classes/instances
    list_accessories: list[Any] = []  # ListAccessory instances rendered above the toolbar

    # Form displays
    form_displays: list[Any] = []  # FormDisplay classes/instances (both create + edit)
    create_displays: list[Any] = []  # Create-only (overrides form_displays for create)
    edit_displays: list[Any] = []  # Edit-only (overrides form_displays for edit)
    default_form_display: Any = None  # Defaults to first in resolved list

    # Bulk operations
    bulk_actions: list[Any] = []  # Opt-in: [BulkAction.DELETE, BulkAction.UPDATE]

    # RSS/Atom feeds (apps.feeds). Opt-in: publish this model as a feed at
    # /feed/<slug>.rss (+ .atom). Item fields fall back to the search
    # declarations, so a single flag usually suffices.
    enable_rss = False
    rss_slug = None            # feed slug; defaults to url_base (slashes → dashes)
    rss_title_field = None     # <item> title; defaults to search_display, else str(obj)
    rss_description_field = None  # <item> description; defaults to search_subtitle
    rss_date_field = None      # <pubDate> source; defaults to a detected timestamp field
    rss_author_field = None    # optional <author>, e.g. "owner__username"
    rss_ordering = None        # defaults to ["-<date_field>"] (else ["-pk"])
    rss_access = None          # SearchAccess level; defaults to search_access
    rss_limit = 50             # max items in the feed
    rss_feed_title = None      # channel <title>; defaults to the model's plural name
    rss_feed_description = None  # channel <description>

    # API
    enable_api = False  # Opt-in: generate JSON API endpoints alongside HTML views
    api_extra_fields: list[str] = []  # Read-only fields appended to API responses (e.g. ["created_at", "updated_at"])
    api_expand_fields: list[str] = []  # FK fields always expanded as {"id": pk, "name": str(obj)} (e.g. ["category"])
    api_aggregate_fields: list[str] = []  # Numeric fields that support sum/avg/min/max aggregation
    ordering_fields: list[str] = []  # Fields allowed for ?ordering= (defaults to sortable list_fields)
    search_fields: list[str] = []  # Fields for ?q= search (reads from admin_class.search_fields)
    filter_fields: list[str] = []  # Fields for query-param filtering (reads from admin_class.list_filter)
    filter_class: Any = None  # Optional django-filters FilterSet class
    export_formats: list[str] = []  # e.g. ["csv", "json"] — enables ?format= on API list

    # Search exposure — opt-in keyword search via FTS5 (SQLite) /
    # SearchVector+GIN (Postgres) / __icontains (fallback). When
    # enable_search=True, the model joins the unified search index
    # and gets:
    #   - A search_<plural> MCP tool that Claude can call directly
    #   - Results in /smallstack/search/?q= and the topbar Ctrl+K omnibar
    #   - GET /api/search/?q= entries
    # search_fields above is reused for the indexed columns.
    # Optional knobs:
    #   search_display  — field name for the result row title (defaults to str(obj))
    #   search_subtitle — field name for the secondary line (truncated)
    #   search_weight   — {field: int} per-field BM25/ts_rank weight (default 1)
    enable_search = False
    search_display: str | None = None
    search_subtitle: str | None = None
    search_weight: dict | None = None

    # MCP (Model Context Protocol) exposure — opt-in surface for AI clients.
    # When enable_mcp=True, apps.mcp.factory emits list_<base>, get_<singular>,
    # and (when CREATE/UPDATE/DELETE are in `actions`) create_/update_/delete_
    # tools wired through the existing form_class / get_list_queryset / hooks.
    enable_mcp = False
    # Human-readable description for the auto-generated tools. AI clients use
    # this to decide when to call the tool — write it for the LLM, not the dev.
    mcp_description: str | None = None
    # Restrict which CRUD actions become MCP tools. None means "follow
    # `actions`". Use to keep web writes while exposing MCP as read-only.
    mcp_actions: list | None = None
    # Per-action description overrides for finer-grained tool descriptions.
    # Default is f"<verb> {mcp_description or model._meta.verbose_name}".
    # Example: {Action.CREATE: "File a brand-new support ticket."}
    mcp_descriptions: dict | None = None
    # Override the noun used in MCP tool names. Defaults keep upstream
    # behaviour: list_<url_base or verbose_name_plural>, get_/create_/
    # update_/delete_<verbose_name>. Set both for a consistent, custom
    # name pair like ("ticket", "tickets") → list_tickets + get_ticket.
    mcp_singular: str | None = None
    mcp_plural: str | None = None

    # Webhook exposure — opt-in OUTBOUND eventing. When enable_webhooks=True, a
    # create/update/delete of this model (via ANY surface — HTML/REST/MCP/sc/raw
    # ORM) is observed by apps.webhooks.signals and fanned out to matching
    # WebhookEndpoints as a signed HTTP POST. This is the inverse of enable_api /
    # enable_mcp: instead of a client calling in, the app calls out on change.
    # The payload reuses the same serialize() the REST API emits.
    enable_webhooks = False
    # Which lifecycle events emit. None => all three. Members are the strings
    # "created" / "updated" / "deleted" (kept as bare strings to avoid importing
    # webhook enums into the framework core).
    webhook_events: list[str] | None = None

    # Related object tabs (reverse FK relations on detail page)
    related_tabs: Any = None  # None=auto-discover, list=explicit accessor names, False=disabled
    related_tabs_exclude: list[str] = []  # Accessor names to exclude from auto-discovery
    related_tabs_paginate_by = 10

    # Legacy/direct config
    form_class: type[Any] | None = None
    queryset: Any = None
    field_formatters: dict[str, Any] = {}  # Deprecated — use field_transforms
    preview_fields: list[str] = []  # Deprecated — use field_transforms
    field_transforms: dict[str, Any] = {}  # {field_name: "transform_name" | ("name", {opts}) | callable}
    column_widths: dict[str, str] | None = None  # Optional {field_name: "30%"} for custom column proportions

    # -- Config resolution: admin_class → legacy attrs → defaults --

    @classmethod
    def _model(cls) -> type[Model]:
        """The configured model, asserted non-None (every routed CRUDView has one)."""
        assert cls.model is not None, f"{cls.__name__} has no model configured"
        return cls.model

    @classmethod
    def _get_url_base(cls) -> str:
        if cls.url_base:
            return cls.url_base
        return cls._model()._meta.model_name or ""

    @classmethod
    def _reverse(cls, url_name: str, **kwargs) -> str:
        """Reverse a URL name, prepending namespace if set."""
        if cls.namespace:
            return reverse(f"{cls.namespace}:{url_name}", **kwargs)
        return reverse(url_name, **kwargs)

    @classmethod
    def _get_list_fields(cls) -> list[str]:
        # Explicit list_fields always wins
        if cls.list_fields:
            return cls.list_fields
        # Try admin_class.list_display
        if cls.admin_class:
            ld = getattr(cls.admin_class, "list_display", ["__str__"])
            if list(ld) != ["__str__"]:
                model_field_names = {f.name for f in cls._model()._meta.get_fields()}
                fields = [f for f in ld if f in model_field_names and f != "pk"]
                if fields:
                    return fields
        return cls.fields or []

    @classmethod
    def _get_list_columns(cls) -> list[str]:
        """UI-only column subset for the list template. Falls back to list_fields.

        Use this to trim the list table without affecting API/CSV/ordering.
        """
        if cls.list_columns:
            return list(cls.list_columns)
        return cls._get_list_fields()

    @classmethod
    def _get_detail_fields(cls) -> list[str]:
        if cls.detail_fields:
            return cls.detail_fields
        # Try admin_class.fields (flat list) or flatten fieldsets
        if cls.admin_class:
            admin_fields = getattr(cls.admin_class, "fields", None)
            if admin_fields:
                return list(admin_fields)
            fieldsets = getattr(cls.admin_class, "fieldsets", None)
            if fieldsets:
                flat = []
                for _name, opts in fieldsets:
                    flat.extend(opts.get("fields", []))
                if flat:
                    return flat
        # Detail is read-only — show all concrete fields, not just form fields.
        # This ensures fields like TextField notes or auto_now_add timestamps
        # appear even when they aren't in list_display.
        from django.db.models import AutoField, BigAutoField, Field, ForeignKey

        all_fields = []
        for f in cls._model()._meta.get_fields():
            if not isinstance(f, (Field, ForeignKey)):
                continue
            if isinstance(f, (AutoField, BigAutoField)):
                continue
            all_fields.append(f.name)
        return all_fields or cls.fields or []

    @classmethod
    def _get_link_field(cls) -> str | None:
        if cls.link_field:
            return cls.link_field
        list_fields = cls._get_list_fields()
        return list_fields[0] if list_fields else None

    @classmethod
    def _resolve_paginate_by(cls) -> int | None:
        """Resolve pagination: explicit paginate_by → admin_class.list_per_page."""
        if cls.paginate_by is not None:
            return cls.paginate_by
        if cls.admin_class:
            return getattr(cls.admin_class, "list_per_page", None)
        return None

    @classmethod
    def _get_displays(cls) -> list:
        """Return list of display instances for the list view."""
        if not cls.displays:
            return []
        return [d() if isinstance(d, type) else d for d in cls.displays]

    @classmethod
    def _get_detail_displays(cls) -> list:
        """Return list of display instances for the detail view."""
        if not cls.detail_displays:
            from .displays import DetailGridDisplay

            return [DetailGridDisplay()]
        return [d() if isinstance(d, type) else d for d in cls.detail_displays]

    @classmethod
    def _get_form_displays(cls, action: str = "form") -> list:
        """Return list of form display instances for create or edit.

        Resolution: create_displays/edit_displays → form_displays → empty.
        """
        if action == "create" and cls.create_displays:
            source = cls.create_displays
        elif action == "edit" and cls.edit_displays:
            source = cls.edit_displays
        elif cls.form_displays:
            source = cls.form_displays
        else:
            return []
        return [d() if isinstance(d, type) else d for d in source]

    @classmethod
    def _get_effective_transforms(cls) -> dict[str, Any]:
        """Merge legacy attrs (preview_fields, field_formatters) into field_transforms.

        Priority: explicit field_transforms > preview_fields > field_formatters.
        Emits deprecation warnings when legacy attrs are non-empty.
        """
        merged = {}

        # Legacy: field_formatters → pass callable through
        if cls.field_formatters:
            warnings.warn(
                f"{cls.__name__}.field_formatters is deprecated, use field_transforms instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            for field_name, formatter in cls.field_formatters.items():
                merged[field_name] = formatter

        # Legacy: preview_fields → map to "preview" transform
        if cls.preview_fields:
            warnings.warn(
                f"{cls.__name__}.preview_fields is deprecated, use field_transforms instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            for field_name in cls.preview_fields:
                merged[field_name] = "preview"

        # Explicit field_transforms wins
        merged.update(cls.field_transforms)

        return merged

    @classmethod
    def _get_related_tabs(cls) -> list[dict[str, Any]]:
        """Return list of related tab dicts for reverse FK relations.

        Each dict: {"accessor", "verbose_name", "related_model", "related_crud", "field_name"}
        Only includes relations whose related model has a registered CRUDView.
        """

        if cls.related_tabs is False:
            return []

        from django.db.models.fields.reverse_related import ForeignObjectRel
        from django.urls import NoReverseMatch

        tabs = []
        for rel in cls._model()._meta.get_fields():
            # Reverse FK relations only — narrows rel to ForeignObjectRel, which
            # carries get_accessor_name()/field (a plain Field does not).
            if not isinstance(rel, ForeignObjectRel) or not rel.one_to_many:
                continue
            related_model = rel.related_model
            if related_model is None:
                continue
            related_crud = CRUDView._registry.get(related_model)
            if not related_crud:
                continue
            # Skip registry entries whose URLs aren't wired (e.g. CRUDViews
            # defined only for MCP exposure, or test-only subclasses). They
            # belong in `_registry` for the MCP factory, but they don't have
            # HTML pages to deep-link to.
            try:
                related_crud._reverse(f"{related_crud._get_url_base()}-list")
            except NoReverseMatch:
                continue
            accessor = rel.get_accessor_name()
            # Find the FK field name on the related model
            field_name = rel.field.name if hasattr(rel, "field") else None
            tabs.append(
                {
                    "accessor": accessor,
                    "verbose_name": str(related_model._meta.verbose_name_plural).capitalize(),
                    "related_model": related_model,
                    "related_crud": related_crud,
                    "field_name": field_name,
                }
            )

        # If explicit list, filter and preserve user's order
        if cls.related_tabs is not None:
            by_accessor = {t["accessor"]: t for t in tabs}
            tabs = [by_accessor[a] for a in cls.related_tabs if a in by_accessor]

        # Apply excludes
        if cls.related_tabs_exclude:
            exclude_set = set(cls.related_tabs_exclude)
            tabs = [t for t in tabs if t["accessor"] not in exclude_set]

        return tabs

    @classmethod
    def _resolve_search_fields(cls) -> list[str]:
        """Resolve search fields: explicit → admin_class.search_fields."""
        if cls.search_fields:
            return list(cls.search_fields)
        if cls.admin_class:
            return list(getattr(cls.admin_class, "search_fields", []))
        return []

    @classmethod
    def _resolve_filter_fields(cls) -> list[str]:
        """Resolve filter fields: explicit → admin_class.list_filter."""
        if cls.filter_fields:
            return list(cls.filter_fields)
        if cls.admin_class:
            raw = getattr(cls.admin_class, "list_filter", [])
            # list_filter can contain strings, (field, FilterClass) tuples,
            # or bare filter classes — skip classes we can't resolve to a field name
            resolved = []
            for f in raw:
                if isinstance(f, str):
                    resolved.append(f)
                elif isinstance(f, (list, tuple)) and f:
                    resolved.append(f[0])
                # bare filter classes (e.g. IsLockedOutFilter) are skipped
            return resolved
        return []

    @classmethod
    def _resolve_filter_class(cls) -> type | None:
        """Return the filter class, or None."""
        return cls.filter_class

    @classmethod
    def _resolve_export_formats(cls) -> list[str]:
        """Return enabled export formats."""
        return cls.export_formats or []

    # -- Hooks for subclass overrides --

    @classmethod
    def can_update(cls, obj, request) -> bool:
        """Return True if the user can update this object. Override for row-level perms."""
        return True

    @classmethod
    def can_delete(cls, obj, request) -> bool:
        """Return True if the user can delete this object. Override for row-level perms."""
        return True

    def rss_item_extra(self, obj: Any) -> dict[str, Any]:
        """Extra ``<item>`` fields for the RSS/Atom feed (when ``enable_rss``).

        Returns a dict merged into Django ``feedgenerator.add_item`` kwargs, so
        override it to attach an ``enclosure`` (podcasts/media), ``categories``,
        or a computed ``author_name``. Default: nothing extra. This is the seam
        that lets a downstream build media feeds without changing the core.
        """
        return {}

    @classmethod
    def row_actions(cls, obj, request, default_actions):
        """Per-row hook to filter the actions rendered for ``obj`` in the
        list view (TableDisplay et al.).

        Receives the default action list (each item is a dict with at
        least ``url`` and ``label``; delete actions also carry
        ``is_delete: True``) and returns whatever subset should render
        for this row. Override to hide e.g. ``Delete`` for the current
        user's own row, or to suppress ``Edit`` for archived items.

        Default: return the full list unchanged.

        Example — protect against self-delete on a User CRUDView::

            @classmethod
            def row_actions(cls, obj, request, default_actions):
                if request and obj.pk == getattr(request.user, "pk", None):
                    return [a for a in default_actions if not a.get("is_delete")]
                return default_actions

        Note: ``can_update`` / ``can_delete`` still gate the actual write
        when the action is invoked. ``row_actions`` is the *render-time*
        filter — using it alone leaves the action endpoint callable
        directly via URL; pair both for defense in depth.
        """
        return default_actions

    @classmethod
    def row_link_url(cls, obj, request):
        """Per-row hook for where the list view's link column points.

        By default a row's name links to the detail page (or the edit page when the
        CRUDView has no DETAIL action). Override to send rows somewhere else — e.g.
        link a monitored-endpoint row to its status timeline instead of its edit form.
        Return ``None`` to keep the default target.
        """
        return None

    @classmethod
    def get_list_queryset(cls, qs, request):
        """Filter the list queryset per-request. Override for tenant scoping, etc."""
        return qs

    @classmethod
    def get_detail_queryset(cls, qs, request):
        """Scope a SINGLE-object fetch (detail / edit / delete / related tab).

        Defaults to :meth:`get_list_queryset` so a row hidden from the list is
        not silently readable — or editable — at its own URL. Override only when
        the list hook does list-specific work you don't want on a detail load
        (e.g. approvals' lazy expiry sweep); keep the *scoping* identical.
        """
        return cls.get_list_queryset(qs, request)

    @classmethod
    def apply_filter(cls, qs, field_name, value, request):
        """Override how ONE ``filter_fields`` entry narrows the queryset.

        Return a queryset to take over, or ``NotImplemented`` (the default) to
        let the built-in per-type handling run. Applies to the HTML list, the
        REST list and the generated MCP ``list_*`` tool, so ``?status=pending``
        means the same thing on all three.

        Exists because a stored column is not always the value the rest of the
        page reasons about. Approvals' expiry is lazy, so an overdue row's
        ``status`` is still ``"pending"`` in the database until a sweep flips it —
        which had ``?status=pending`` listing 905 rows beside its own "Pending"
        stat card reading 5. Whatever a card counts and whatever the filter
        selects should be *one* expression; this is where you say so.
        """
        return NotImplemented

    @classmethod
    def check_object_permission(cls, obj, request) -> None:
        """Per-object authorization for EVERY single-object surface.

        Raise :class:`~django.core.exceptions.PermissionDenied` (403) or
        :class:`~django.http.Http404` to refuse. Called once the object has been
        fetched, from detail, edit, delete, field-preview, related-tab, the REST
        detail/update/delete handlers, the bulk-action view and the generated MCP
        ``get_*``/``update_*``/``delete_*`` tools — so a check written here cannot
        be bypassed by reaching for a less-travelled route.

        Use it instead of overriding a single view's ``get_object``: that covers
        one of the five generated single-object bases, which is how
        ``/…/<pk>/related/<accessor>/`` leaked another user's child rows while the
        detail page beside it correctly answered 403.

        Prefer :meth:`get_detail_queryset` when "not yours" should read as 404
        (existence is a secret). Use this hook when it should read as 403, or
        when the rule is not expressible as a queryset filter.
        """
        return None

    @classmethod
    def on_form_valid(cls, request, form, obj, is_create=False):
        """Hook called after successful create/update. Override for side effects."""
        pass

    @classmethod
    def can_bulk_update_fields(cls) -> list[str]:
        """Return list of field names allowed for bulk update. Override to restrict."""
        return cls.fields or []

    @classmethod
    def _get_queryset(cls):
        if cls.queryset is not None:
            return cls.queryset.all()
        return cls.model.objects.all()

    @classmethod
    def _get_template_names(cls, suffix):
        """Return template list with instance → app → default fallback.

        Resolution order (first match wins):
        1. {namespace}/crud/{model}_{suffix}.html  — instance-specific override
        2. {app_label}/crud/{model}_{suffix}.html  — shared custom template
        3. smallstack/crud/object_{suffix}.html     — default

        Named Explorer instances inherit shared custom templates from step 2
        automatically. Only add a step-1 template when an instance needs its
        own version of a view for that model.
        """
        app_label = cls.model._meta.app_label
        model_name = cls.model._meta.model_name

        templates = []

        # Instance-specific override (only for named child sites)
        if cls.namespace:
            templates.append(f"{cls.namespace}/crud/{model_name}_{suffix}.html")
            if suffix in ("create", "edit"):
                templates.append(f"{cls.namespace}/crud/{model_name}_form.html")

        # Shared app-level custom template
        templates.append(f"{app_label}/crud/{model_name}_{suffix}.html")
        if suffix in ("create", "edit"):
            templates.append(f"{app_label}/crud/{model_name}_form.html")

        # Default
        templates.append(f"smallstack/crud/object_{suffix}.html")
        if suffix in ("create", "edit"):
            templates.append("smallstack/crud/object_form.html")

        return templates

    @classmethod
    def _make_form_class(cls):
        """Auto-generate a ModelForm with proper widgets and styling."""
        _model = cls.model
        _fields = cls.fields

        # Drop non-editable model fields (auto_now / auto_now_add / AutoField pk)
        # from the generated form. Listing one in `fields` — natural for a
        # read-only ingest/audit column — otherwise makes the ModelForm metaclass
        # raise FieldError, which surfaces as a 500 on /api/schema for a view that
        # may not even expose create/update. Such fields stay available for
        # display and `api_extra_fields`; they simply can't be form inputs.
        if isinstance(_fields, (list, tuple)):
            _non_editable = {
                f.name
                for f in _model._meta.get_fields()
                if hasattr(f, "editable") and not f.editable
            }
            _fields = [f for f in _fields if f not in _non_editable]

        class AutoCRUDForm(forms.ModelForm):
            class Meta:
                model = _model
                fields = _fields

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                for field in self.fields.values():
                    widget = field.widget
                    # Date/time fields: use native browser widgets
                    if isinstance(widget, forms.DateTimeInput):
                        field.widget = forms.DateTimeInput(
                            attrs={"type": "datetime-local", **widget.attrs},
                            format="%Y-%m-%dT%H:%M",
                        )
                        field.input_formats = ["%Y-%m-%dT%H:%M"]
                    elif isinstance(widget, forms.DateInput):
                        field.widget = forms.DateInput(
                            attrs={"type": "date", **widget.attrs},
                            format="%Y-%m-%d",
                        )
                        field.input_formats = ["%Y-%m-%d"]
                    elif isinstance(widget, forms.TimeInput):
                        field.widget = forms.TimeInput(
                            attrs={"type": "time", **widget.attrs},
                            format="%H:%M",
                        )
                        field.input_formats = ["%H:%M"]
                    elif isinstance(
                        widget,
                        (
                            forms.TextInput,
                            forms.EmailInput,
                            forms.URLInput,
                            forms.NumberInput,
                            forms.PasswordInput,
                            forms.Textarea,
                        ),
                    ):
                        widget.attrs.setdefault("class", "vTextField")

        return AutoCRUDForm

    @classmethod
    def _resolved_mixins(cls) -> list:
        """The effective auth mixins for every generated view (HTML + REST).

        Secure by default: an unset ``mixins`` (``None``) requires login; set
        ``public = True`` for anonymous access. An explicit ``mixins`` list
        (including ``[]`` or ``[StaffRequiredMixin]``) always wins — this only
        changes the behavior of a view that set *neither*.
        """
        if cls.mixins is not None:
            return list(cls.mixins)
        if cls.public:
            return []
        from django.contrib.auth.mixins import LoginRequiredMixin

        return [LoginRequiredMixin]

    @classmethod
    def _pk_converter(cls):
        """The URL path converter for this model's pk: ``int``, ``uuid`` or ``str``.

        The HTML routes used a bare ``<pk>`` (the ``str`` converter), so a
        non-numeric segment — a crawler, a stale link, ``/requests/search/`` —
        reached the ORM and raised ``ValueError: Field 'id' expected a number but
        got 'search'``, i.e. a 500 in error monitoring for every CRUDView in the
        project. The REST routes always used ``<int:pk>`` and 404'd correctly;
        this makes the HTML routes agree. (F-22.)

        Note the ``uuid`` converter accepts only the **canonical** dashed
        lowercase spelling, so a non-canonical UUID in a bookmark or a log link
        404s where a bare ``<pk>`` used to resolve it. That is a deliberate
        tightening, recorded in ``UPGRADING.md``; ``_coerce_pks`` is deliberately
        laxer for bulk ``ids``, which are data rather than routes. (F-38.)
        """
        field = cls.model._meta.pk
        # A FK/O2O primary key (multi-table inheritance — the ordinary way to get
        # one) reports its OWN internal type, not the column's, so it fell
        # through to `str:` while the underlying column is an integer — the
        # original 500 surviving for that pk class. Follow the relation to the
        # field that actually stores the value. (F-38.)
        seen: set[Any] = set()
        while field.is_relation and field.target_field is not field:
            if id(field) in seen:  # pathological self-reference; stop rather than spin
                break
            seen.add(id(field))
            field = field.target_field
        internal = field.get_internal_type()
        if internal in {
            "AutoField",
            "BigAutoField",
            "SmallAutoField",
            "IntegerField",
            "BigIntegerField",
            "SmallIntegerField",
            "PositiveIntegerField",
            "PositiveBigIntegerField",
            "PositiveSmallIntegerField",
        }:
            return "int:"
        if internal == "UUIDField":
            return "uuid:"
        return "str:"

    @classmethod
    def _coerce_pks(cls, raw):
        """Coerce a list of wire pks to this model's pk type, or raise ValueError.

        The bulk paths hardcoded ``int(pk)``, so a UUID-pk model's bulk action was
        unusable — a flat ``400 Invalid IDs`` — which is the same asymmetry
        ``_pk_converter`` removed from the routes: the URLs learned the pk type,
        the bulk view did not. Uses the model field's own converter, so it follows
        whatever pk class the model declares. (F-38.)
        """
        field = cls.model._meta.pk
        return [field.to_python(pk) for pk in raw]

    @classmethod
    def _make_view(cls, base_class):
        """Create a view class with mixins applied."""
        name = f"{cls.model.__name__}{base_class.__name__.lstrip('_')}"
        bases = tuple(cls._resolved_mixins()) + (base_class,)
        resolved_paginate_by = cls._resolve_paginate_by()
        # When displays are configured, the display handles pagination —
        # skip Django's built-in paginate_by.
        if base_class is _CRUDListBase and cls.displays:
            resolved_paginate_by = None
        return type(
            name,
            bases,
            {
                "model": cls.model,
                "paginate_by": resolved_paginate_by,
                "crud_config": cls,
            },
        )

    @classmethod
    def get_urls(cls):
        """Generate URL patterns for configured actions."""
        # Register model→CRUDView mapping for related tabs discovery.
        # First-wins (see _registry docstring): don't displace a previously-
        # registered class for the same model.
        CRUDView._registry.setdefault(cls.model, cls)

        url_base = cls._get_url_base()
        # Typed pk converter so a non-numeric segment 404s instead of 500ing
        # inside the ORM (F-22).
        pk = f"<{cls._pk_converter()}pk>"
        urls = []

        if Action.LIST in cls.actions:
            view = cls._make_view(_CRUDListBase)
            urls.append(path(f"{url_base}/", view.as_view(), name=f"{url_base}-list"))
            preview_view = cls._make_view(_CRUDFieldPreviewBase)
            urls.append(
                path(
                    f"{url_base}/{pk}/field-preview/<str:field_name>/",
                    preview_view.as_view(),
                    name=f"{url_base}-field-preview",
                )
            )

        if Action.CREATE in cls.actions:
            view = cls._make_view(_CRUDCreateBase)
            urls.append(path(f"{url_base}/new/", view.as_view(), name=f"{url_base}-create"))

        # Bulk action endpoints (opt-in) — must be before <pk>/ detail catch-all
        if cls.bulk_actions:
            bulk_view_cls = type(
                f"{cls.model.__name__}BulkAction",
                (_CRUDBulkActionView,),
                {"crud_config": cls},
            )
            urls.append(path(f"{url_base}/bulk/", bulk_view_cls.as_view(), name=f"{url_base}-bulk"))
            if BulkAction.UPDATE in cls.bulk_actions:
                urls.append(
                    path(
                        f"{url_base}/bulk/update-form/",
                        _make_bulk_update_form_view(cls),
                        name=f"{url_base}-bulk-update-form",
                    )
                )

        if Action.DETAIL in cls.actions:
            view = cls._make_view(_CRUDDetailBase)
            urls.append(path(f"{url_base}/{pk}/", view.as_view(), name=f"{url_base}-detail"))

            # Related tabs endpoint (lazy HTMX loading)
            if cls.related_tabs is not False:
                related_view = cls._make_view(_CRUDRelatedTabBase)
                urls.append(
                    path(
                        f"{url_base}/{pk}/related/<str:accessor>/",
                        related_view.as_view(),
                        name=f"{url_base}-related-tab",
                    )
                )

        if Action.UPDATE in cls.actions:
            view = cls._make_view(_CRUDUpdateBase)
            urls.append(path(f"{url_base}/{pk}/edit/", view.as_view(), name=f"{url_base}-update"))

        if Action.DELETE in cls.actions:
            view = cls._make_view(_CRUDDeleteBase)
            urls.append(path(f"{url_base}/{pk}/delete/", view.as_view(), name=f"{url_base}-delete"))

        # API endpoints (opt-in per CRUDView, and gated site-wide by
        # SMALLSTACK_API_ENABLED — off ⇒ enable_api is a no-op, registry stays empty).
        from django.conf import settings

        if cls.enable_api and getattr(settings, "SMALLSTACK_API_ENABLED", True):
            from .api import build_api_urls

            urls.extend(build_api_urls(cls))

        return urls
