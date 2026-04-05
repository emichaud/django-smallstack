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
import warnings

from django import forms
from django.contrib import messages
from django.db import IntegrityError
from django.db.models import ProtectedError, RestrictedError
from django.http import Http404, HttpResponse, QueryDict
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


def _apply_list_search(qs, request, crud_config):
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
    date_filters = None
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


def _apply_ordering_fields(qs, ordering, allowed):
    """Apply comma-separated ordering fields to a queryset.

    Each field may be prefixed with ``-`` for descending.  Fields not in
    *allowed* are silently ignored (matches Django/DRF convention).

    This is the low-level helper used by both the HTML list view and the
    REST API layer.
    """
    validated = []
    for part in ordering.split(","):
        field = part.strip().lstrip("-")
        if field in allowed:
            validated.append(part.strip())
    if validated:
        return qs.order_by(*validated)
    return qs


def _apply_ordering(qs, request, crud_config):
    """Apply ?ordering= sort to a queryset using list_fields as allowed fields.

    The allowed set is derived from ``ordering_fields`` (if set) or
    ``list_fields``, restricted to real model fields (computed/transform-only
    columns are excluded).
    """
    ordering = request.GET.get("ordering", "").strip()
    if not ordering:
        return qs

    # Build allowed set: ordering_fields override, else list_fields filtered to model fields
    allowed = set(getattr(crud_config, "ordering_fields", None) or [])
    if not allowed:
        model_field_names = {f.name for f in crud_config.model._meta.get_fields()}
        allowed = {f for f in crud_config._get_list_fields() if f in model_field_names}

    return _apply_ordering_fields(qs, ordering, allowed)


def _apply_list_filters(qs, request, crud_config):
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


def _build_toolbar_context(request, crud_config):
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


def _build_filter_meta(model, field_name):
    """Build filter widget metadata for a single field."""
    from django.db import models as _m

    try:
        field = model._meta.get_field(field_name)
    except Exception:
        return None

    meta = {
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
            objects = related_model.objects.all()[:100]
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

    crud_config = None  # Set by CRUDView._make_view()

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
        elif cfg.table_class:
            # Legacy table2 path (no displays configured, but table_class set)
            warnings.warn(
                f"{cfg.__name__}.table_class is deprecated. Use TableDisplay "
                "instead — the built-in table now supports column sorting.",
                DeprecationWarning,
                stacklevel=2,
            )
            from django_tables2 import RequestConfig

            table = cfg.table_class(qs)
            paginate = {"per_page": cfg.paginate_by} if cfg.paginate_by else False
            RequestConfig(self.request, paginate=paginate).configure(table)
            context["table"] = table
            context["use_tables2"] = True
        else:
            # Legacy basic table path — pagination display helpers
            page_obj = context.get("page_obj")
            if page_obj:
                page_obj.showing_start = page_obj.start_index()
                page_obj.showing_end = page_obj.end_index()
                page_obj.total_count = page_obj.paginator.count
                page_obj.page_range_display = page_obj.paginator.get_elided_page_range(
                    page_obj.number, on_each_side=2, on_ends=1
                )
        return context


class _CRUDDetailBase(_CRUDContextMixin, DetailView):
    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            display = self._get_active_detail_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
        return self.crud_config._get_template_names("detail")

    def get_queryset(self):
        return self.crud_config._get_queryset()

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

    def get_success_url(self):
        return self.crud_config._reverse(f"{self.crud_config._get_url_base()}-list")


class _CRUDUpdateBase(_CRUDFormDisplayMixin, _CRUDContextMixin, UpdateView):
    _form_action = "edit"

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            display = self._get_active_form_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
        return self.crud_config._get_template_names("edit")

    def get_queryset(self):
        return self.crud_config._get_queryset()

    def get_form_class(self):
        return self.crud_config.form_class or self.crud_config._make_form_class()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return self._inject_display_context(context, obj=self.object)

    def get_success_url(self):
        return self.crud_config._reverse(f"{self.crud_config._get_url_base()}-detail", kwargs={"pk": self.object.pk})


class _CRUDDeleteBase(_CRUDContextMixin, DeleteView):
    def get_template_names(self):
        return self.crud_config._get_template_names("confirm_delete")

    def get_queryset(self):
        return self.crud_config._get_queryset()

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
            msg = "Delete failed — an unexpected error occurred."
        else:
            return  # unreachable, but keeps linters happy
        if getattr(request, "htmx", False) or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return HttpResponse(msg, status=409)
        messages.error(request, msg)
        return _redirect(self.get_success_url())


class _CRUDBulkActionView:
    """Handles bulk delete and bulk update operations via POST.

    Processes objects individually to respect per-object permission hooks
    and catch ProtectedError per row.
    """

    crud_config = None

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
                    ids = [int(pk) for pk in ids]
                except (ValueError, TypeError):
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

                qs = cfg._get_queryset().filter(pk__in=ids)
                objects = {obj.pk: obj for obj in qs}
                deleted_ids = []
                errors = {}

                for pk in ids:
                    obj = objects.get(pk)
                    if obj is None:
                        errors[str(pk)] = "Not found"
                        continue
                    if not cfg.can_delete(obj, request):
                        errors[str(pk)] = "Permission denied"
                        continue
                    try:
                        obj.delete()
                        deleted_ids.append(pk)
                    except (ProtectedError, RestrictedError) as e:
                        protected = getattr(e, "protected_objects", None) or getattr(e, "restricted_objects", set())
                        name = type(next(iter(protected))).__name__ if protected else "other records"
                        cnt = len(protected)
                        s = "s" if cnt != 1 else ""
                        errors[str(pk)] = f"Cannot delete — {cnt} {name} record{s} still linked."
                    except IntegrityError:
                        errors[str(pk)] = "Cannot delete — a database constraint prevented this action."
                    except Exception:
                        errors[str(pk)] = "Delete failed — an unexpected error occurred."

                msg = f"Deleted {len(deleted_ids)} of {len(ids)}"

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

                qs = cfg._get_queryset().filter(pk__in=ids)
                objects = {obj.pk: obj for obj in qs}
                updated = []
                errors = {}

                for pk in ids:
                    obj = objects.get(pk)
                    if obj is None:
                        errors[str(pk)] = "Not found"
                        continue
                    if not cfg.can_update(obj, request):
                        errors[str(pk)] = "Permission denied"
                        continue

                    # Build PATCH-style form: merge existing values with new fields
                    from django.forms.models import model_to_dict

                    existing = model_to_dict(obj, fields=cfg.fields or [])
                    merged = QueryDict(mutable=True)
                    for key, value in existing.items():
                        if value is None:
                            merged[key] = ""
                        elif isinstance(value, list):
                            merged.setlist(key, [str(v) for v in value])
                        else:
                            merged[key] = str(value)
                    for key, value in fields_data.items():
                        merged[key] = str(value) if value is not None else ""

                    form_class = cfg.form_class or cfg._make_form_class()
                    form = form_class(merged, instance=obj)
                    if form.is_valid():
                        obj = form.save()
                        cfg.on_form_valid(request, form, obj, is_create=False)
                        updated.append(pk)
                    else:
                        errors[str(pk)] = {k: [str(e) for e in v] for k, v in form.errors.items()}

                total = len(ids)
                updated_count = len(updated)
                msg = f"Updated {updated_count} of {total}"

                return HttpResponse(
                    _json.dumps({"updated": updated, "errors": errors, "message": msg}),
                    content_type="application/json",
                )

        # Apply mixins
        bases = tuple(config.mixins) + (BulkView,)
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
    bases = tuple(config.mixins) + (BulkUpdateFormView,)
    view_cls = type(f"{config.model.__name__}BulkUpdateFormView", bases, {})
    return view_cls.as_view()


class _CRUDFieldPreviewBase(_CRUDContextMixin, DetailView):
    """Server-rendered field preview partial, loaded via HTMX."""

    def get_queryset(self):
        return self.crud_config._get_queryset()

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


# ---------------------------------------------------------------------------
# Transform spec resolution
# ---------------------------------------------------------------------------


def _resolve_transform_spec(spec):
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
        table_class:      Optional django-tables2 Table class for enhanced list view
        preview_fields:   Deprecated — use field_transforms
        field_transforms: {field_name: "transform_name" | ("name", {opts}) | callable}
    """

    # Config source
    admin_class = None  # ModelAdmin subclass — the standard Django config DSL

    # Model/data
    model = None
    fields = None
    list_fields = None
    list_columns = None  # Optional UI-only override: narrower column set for list template (API/CSV still use list_fields)
    detail_fields = None
    link_field = None

    # View/routing
    url_base = None
    namespace: str | None = None  # URL namespace for child ExplorerSite instances
    paginate_by = 25
    mixins = []
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = None  # Optional (label, url_name) for parent breadcrumb

    # Display
    displays = []  # List of ListDisplay classes/instances. Empty = legacy auto-detect.
    default_display = None  # Defaults to first in displays
    detail_displays = []  # List of DetailDisplay classes/instances
    list_accessories = []  # ListAccessory instances rendered above the toolbar

    # Form displays
    form_displays = []  # FormDisplay classes/instances (both create + edit)
    create_displays = []  # Create-only (overrides form_displays for create)
    edit_displays = []  # Edit-only (overrides form_displays for edit)
    default_form_display = None  # Defaults to first in resolved list

    # Bulk operations
    bulk_actions = []  # Opt-in: [BulkAction.DELETE, BulkAction.UPDATE]

    # API
    enable_api = False  # Opt-in: generate JSON API endpoints alongside HTML views
    api_extra_fields = []  # Extra read-only fields appended to API responses (e.g. ["created_at", "updated_at"])
    api_expand_fields = []  # FK fields always expanded as {"id": pk, "name": str(obj)} (e.g. ["category"])
    api_aggregate_fields = []  # Numeric fields that support sum/avg/min/max aggregation
    ordering_fields = []  # Fields allowed for ?ordering= (defaults to sortable list_fields)
    search_fields = []  # Fields for ?q= search (reads from admin_class.search_fields)
    filter_fields = []  # Fields for query-param filtering (reads from admin_class.list_filter)
    filter_class = None  # Optional django-filters FilterSet class
    export_formats = []  # e.g. ["csv", "json"] — enables ?format= on API list

    # Legacy/direct config
    form_class = None
    queryset = None
    field_formatters = {}  # Deprecated — use field_transforms
    table_class = None  # Optional django-tables2 Table class for enhanced list view
    preview_fields = []  # Deprecated — use field_transforms
    field_transforms = {}  # {field_name: "transform_name" | ("name", {opts}) | callable}
    column_widths = None  # Optional {field_name: "30%"} for custom column proportions

    # -- Config resolution: admin_class → legacy attrs → defaults --

    @classmethod
    def _get_url_base(cls):
        if cls.url_base:
            return cls.url_base
        return cls.model._meta.model_name

    @classmethod
    def _reverse(cls, url_name: str, **kwargs) -> str:
        """Reverse a URL name, prepending namespace if set."""
        if cls.namespace:
            return reverse(f"{cls.namespace}:{url_name}", **kwargs)
        return reverse(url_name, **kwargs)

    @classmethod
    def _get_list_fields(cls):
        # Explicit list_fields always wins
        if cls.list_fields:
            return cls.list_fields
        # Try admin_class.list_display
        if cls.admin_class:
            ld = getattr(cls.admin_class, "list_display", ["__str__"])
            if list(ld) != ["__str__"]:
                model_field_names = {f.name for f in cls.model._meta.get_fields()}
                fields = [f for f in ld if f in model_field_names and f != "pk"]
                if fields:
                    return fields
        return cls.fields

    @classmethod
    def _get_list_columns(cls):
        """UI-only column subset for the list template. Falls back to list_fields.

        Use this to trim the list table without affecting API/CSV/ordering.
        """
        if cls.list_columns:
            return list(cls.list_columns)
        return cls._get_list_fields()

    @classmethod
    def _get_detail_fields(cls):
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
        for f in cls.model._meta.get_fields():
            if not isinstance(f, (Field, ForeignKey)):
                continue
            if isinstance(f, (AutoField, BigAutoField)):
                continue
            all_fields.append(f.name)
        return all_fields or cls.fields

    @classmethod
    def _get_link_field(cls):
        if cls.link_field:
            return cls.link_field
        list_fields = cls._get_list_fields()
        return list_fields[0] if list_fields else None

    @classmethod
    def _resolve_paginate_by(cls):
        """Resolve pagination: explicit paginate_by → admin_class.list_per_page."""
        if cls.paginate_by is not None:
            return cls.paginate_by
        if cls.admin_class:
            return getattr(cls.admin_class, "list_per_page", None)
        return None

    @classmethod
    def _get_displays(cls):
        """Return list of display instances for the list view."""
        if not cls.displays:
            return []
        return [d() if isinstance(d, type) else d for d in cls.displays]

    @classmethod
    def _get_detail_displays(cls):
        """Return list of display instances for the detail view."""
        if not cls.detail_displays:
            from .displays import DetailGridDisplay

            return [DetailGridDisplay()]
        return [d() if isinstance(d, type) else d for d in cls.detail_displays]

    @classmethod
    def _get_form_displays(cls, action="form"):
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
    def _get_effective_transforms(cls):
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
    def _resolve_search_fields(cls):
        """Resolve search fields: explicit → admin_class.search_fields."""
        if cls.search_fields:
            return list(cls.search_fields)
        if cls.admin_class:
            return list(getattr(cls.admin_class, "search_fields", []))
        return []

    @classmethod
    def _resolve_filter_fields(cls):
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
    def _resolve_filter_class(cls):
        """Return the filter class, or None."""
        return cls.filter_class

    @classmethod
    def _resolve_export_formats(cls):
        """Return enabled export formats."""
        return cls.export_formats or []

    # -- Hooks for subclass overrides --

    @classmethod
    def can_update(cls, obj, request):
        """Return True if the user can update this object. Override for row-level perms."""
        return True

    @classmethod
    def can_delete(cls, obj, request):
        """Return True if the user can delete this object. Override for row-level perms."""
        return True

    @classmethod
    def get_list_queryset(cls, qs, request):
        """Filter the list queryset per-request. Override for tenant scoping, etc."""
        return qs

    @classmethod
    def on_form_valid(cls, request, form, obj, is_create=False):
        """Hook called after successful create/update. Override for side effects."""
        pass

    @classmethod
    def can_bulk_update_fields(cls):
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
    def _make_view(cls, base_class):
        """Create a view class with mixins applied."""
        name = f"{cls.model.__name__}{base_class.__name__.lstrip('_')}"
        bases = tuple(cls.mixins) + (base_class,)
        resolved_paginate_by = cls._resolve_paginate_by()
        # When displays are configured or table_class is set, the display/table
        # handles pagination — skip Django's built-in paginate_by.
        if base_class is _CRUDListBase and (cls.displays or cls.table_class):
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
        url_base = cls._get_url_base()
        urls = []

        if Action.LIST in cls.actions:
            view = cls._make_view(_CRUDListBase)
            urls.append(path(f"{url_base}/", view.as_view(), name=f"{url_base}-list"))
            preview_view = cls._make_view(_CRUDFieldPreviewBase)
            urls.append(
                path(
                    f"{url_base}/<pk>/field-preview/<str:field_name>/",
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
            urls.append(path(f"{url_base}/<pk>/", view.as_view(), name=f"{url_base}-detail"))

        if Action.UPDATE in cls.actions:
            view = cls._make_view(_CRUDUpdateBase)
            urls.append(path(f"{url_base}/<pk>/edit/", view.as_view(), name=f"{url_base}-update"))

        if Action.DELETE in cls.actions:
            view = cls._make_view(_CRUDDeleteBase)
            urls.append(path(f"{url_base}/<pk>/delete/", view.as_view(), name=f"{url_base}-delete"))

        # API endpoints (opt-in)
        if cls.enable_api:
            from .api import build_api_urls

            urls.extend(build_api_urls(cls))

        return urls
