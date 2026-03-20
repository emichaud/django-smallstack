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
from django.http import Http404
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


# ---------------------------------------------------------------------------
# Internal base view classes
# ---------------------------------------------------------------------------


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
                "object_verbose_name": str(meta.verbose_name).capitalize(),
                "object_verbose_name_plural": str(meta.verbose_name_plural).capitalize(),
                "url_base": url_base,
                "list_fields": cfg._get_list_fields(),
                "detail_fields": cfg._get_detail_fields(),
                "link_field": cfg._get_link_field(),
                "crud_actions": cfg.actions,
                "field_transforms": cfg._get_effective_transforms(),
                # Legacy keys for backward compat with custom templates
                "field_formatters": cfg.field_formatters,
                "preview_fields": cfg.preview_fields,
            }
        )
        # Optional parent breadcrumb: (label, url_name) tuple
        if cfg.breadcrumb_parent:
            label, url_name = cfg.breadcrumb_parent
            context["breadcrumb_parent_label"] = label
            context["breadcrumb_parent_url_name"] = url_name
        if Action.CREATE in cfg.actions:
            context["create_view_url"] = reverse(f"{url_base}-create")
        if Action.LIST in cfg.actions:
            context["list_view_url"] = reverse(f"{url_base}-list")
            context["list_view_url_name"] = f"{url_base}-list"
        return context


class _CRUDListBase(_CRUDContextMixin, ListView):
    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            # Display swap via HTMX: return just the display template
            display = self._get_active_display()
            if display and self.request.GET.get("display"):
                return [display.template_name]
            return self.crud_config._get_template_names("list_partial")
        return self.crud_config._get_template_names("list")

    def get_queryset(self):
        return self.crud_config._get_queryset()

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

        # Try display protocol first (when displays are configured)
        display = self._get_active_display()
        if display:
            display_ctx = display.get_context(self.get_queryset(), cfg, self.request)
            context.update(display_ctx)
            context["display_template"] = display.template_name
            context["active_display"] = display.name
            all_displays = cfg._get_displays()
            context["display_palette"] = build_palette_context(
                all_displays, display, self.request
            )
            if len(all_displays) > 1:
                context["available_displays"] = all_displays
        elif cfg.table_class:
            # Legacy table2 path (no displays configured, but table_class set)
            from django_tables2 import RequestConfig

            table = cfg.table_class(self.get_queryset())
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
            context["display_palette"] = build_palette_context(
                all_displays, display, self.request
            )
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
            display_ctx = display.get_context(
                context.get("form"), obj, self.crud_config, self.request
            )
            context.update(display_ctx)
            context["display_template"] = display.template_name
            context["active_display"] = display.name
            all_displays = self.crud_config._get_form_displays(self._form_action)
            context["display_palette"] = build_palette_context(
                all_displays, display, self.request
            )
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
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-list")


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
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-detail", kwargs={"pk": self.object.pk})


class _CRUDDeleteBase(_CRUDContextMixin, DeleteView):
    def get_template_names(self):
        return self.crud_config._get_template_names("confirm_delete")

    def get_queryset(self):
        return self.crud_config._get_queryset()

    def get_success_url(self):
        url_base = self.crud_config._get_url_base()
        return reverse(f"{url_base}-list")


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
    detail_fields = None
    link_field = None

    # View/routing
    url_base = None
    paginate_by = None
    mixins = []
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = None  # Optional (label, url_name) for parent breadcrumb

    # Display
    displays = []  # List of ListDisplay classes/instances. Empty = legacy auto-detect.
    default_display = None  # Defaults to first in displays
    detail_displays = []  # List of DetailDisplay classes/instances

    # Form displays
    form_displays = []  # FormDisplay classes/instances (both create + edit)
    create_displays = []  # Create-only (overrides form_displays for create)
    edit_displays = []  # Edit-only (overrides form_displays for edit)
    default_form_display = None  # Defaults to first in resolved list

    # API
    enable_api = False  # Opt-in: generate JSON API endpoints alongside HTML views
    api_extra_fields = []  # Extra read-only fields appended to API responses (e.g. ["created_at", "updated_at"])
    api_expand_fields = []  # FK fields always expanded as {"id": pk, "name": str(obj)} (e.g. ["category"])
    api_aggregate_fields = []  # Numeric fields that support sum/avg/min/max aggregation
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

    # -- Config resolution: admin_class → legacy attrs → defaults --

    @classmethod
    def _get_url_base(cls):
        if cls.url_base:
            return cls.url_base
        return cls.model._meta.model_name

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
        return cls.fields

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
            return []
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
            # list_filter can contain strings or (field, FilterClass) tuples
            return [f if isinstance(f, str) else f[0] for f in raw]
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
    def _get_queryset(cls):
        if cls.queryset is not None:
            return cls.queryset.all()
        return cls.model.objects.all()

    @classmethod
    def _get_template_names(cls, suffix):
        """Return template list: app-specific override first, then default.

        Templates are namespaced under {app_label}/crud/ to avoid collisions
        with public-facing templates that use Django's standard naming
        convention ({app_label}/{model_name}_{suffix}.html).

        For "create" and "edit" suffixes, falls back to "form" for backward
        compatibility — existing {model}_form.html overrides still work.
        """
        app_label = cls.model._meta.app_label
        model_name = cls.model._meta.model_name

        templates = [f"{app_label}/crud/{model_name}_{suffix}.html"]

        # Fallback: create/edit → form (backward compat)
        if suffix in ("create", "edit"):
            templates.append(f"{app_label}/crud/{model_name}_form.html")

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
