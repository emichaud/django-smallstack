"""Explorer registry — manages model registration and CRUDView generation.

Supports three registration paths:
    1. explorer.register() — explicit registration in explorer.py files
    2. explorer.autodiscover() — imports explorer.py from installed apps
    3. explorer.discover_admin() — legacy: scans admin.site for explorer_enabled=True
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

import django_tables2 as tables
from django.db.models import AutoField, BigAutoField, Field, ForeignKey
from django.urls import path, reverse
from django.utils.text import slugify

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.tables import ActionsColumn, DetailLinkColumn

if TYPE_CHECKING:
    from django import forms
    from django.db import models
    from django.urls import URLPattern

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ModelInfo:
    """Metadata for a single Explorer-registered model."""

    app_label: str
    model_name: str
    verbose_name: str
    verbose_name_plural: str
    model_class: type[models.Model]
    url_base: str
    readonly: bool
    group: str
    namespace: str | None = None

    def _reverse(self, url_name: str, **kwargs) -> str:
        """Reverse a URL name, prepending namespace if set."""
        if self.namespace:
            return reverse(f"{self.namespace}:{url_name}", **kwargs)
        return reverse(url_name, **kwargs)

    def with_counts(self) -> ModelCardInfo:
        """Return a ModelCardInfo with live count and resolved list URL."""
        return ModelCardInfo(
            app_label=self.app_label,
            model_name=self.model_name,
            verbose_name=self.verbose_name,
            verbose_name_plural=self.verbose_name_plural,
            model_class=self.model_class,
            url_base=self.url_base,
            readonly=self.readonly,
            group=self.group,
            namespace=self.namespace,
            count=self.model_class.objects.count(),
            list_url=self._reverse(f"{self.url_base}-list"),
        )

    # Allow dict-style access so django-tables2 render_* methods work
    # with record["key"] or record.key interchangeably.
    def __getitem__(self, key: str):
        return getattr(self, key)


@dataclasses.dataclass
class ModelCardInfo(ModelInfo):
    """ModelInfo enriched with live count and resolved list URL."""

    count: int = 0
    list_url: str = ""


@dataclasses.dataclass
class GroupContext:
    """Everything a group page needs for its template context."""

    group_name: str
    models: list[ModelCardInfo]
    all_groups: list[str]

    def as_context(self) -> dict:
        """Return a dict ready for context.update()."""
        return {
            "group_name": self.group_name,
            "models": self.models,
            "all_groups": self.all_groups,
        }


@dataclasses.dataclass
class AppContext:
    """Everything an app page needs for its template context."""

    app_label: str
    app_verbose_name: str
    models: list[ModelCardInfo]
    all_apps: list[str]

    def as_context(self) -> dict:
        """Return a dict ready for context.update()."""
        return {
            "app_label": self.app_label,
            "app_verbose_name": self.app_verbose_name,
            "models": self.models,
            "all_apps": self.all_apps,
        }


@dataclasses.dataclass
class ModelContext:
    """Everything a single-model page needs for its template context."""

    info: ModelCardInfo
    crud_class: type[CRUDView]
    object_verbose_name: str
    object_verbose_name_plural: str
    url_base: str
    list_fields: list[str]
    detail_fields: list[str]
    link_field: str | None
    crud_actions: list[Action]
    field_transforms: dict
    create_view_url: str | None
    # Legacy — kept for backward compat with custom templates
    field_formatters: dict = dataclasses.field(default_factory=dict)
    preview_fields: list[str] = dataclasses.field(default_factory=list)

    def as_context(self) -> dict:
        """Return a dict ready for context.update().

        Includes object_list from the CRUD queryset and all fields
        the crud_table template tag expects.
        """
        return {
            "object_verbose_name": self.object_verbose_name,
            "object_verbose_name_plural": self.object_verbose_name_plural,
            "url_base": self.url_base,
            "list_fields": self.list_fields,
            "detail_fields": self.detail_fields,
            "link_field": self.link_field,
            "crud_actions": self.crud_actions,
            "field_transforms": self.field_transforms,
            # Legacy keys for backward compat with custom templates
            "field_formatters": self.field_formatters,
            "preview_fields": self.preview_fields,
            "create_view_url": self.create_view_url,
            "model_info": self.info,
            "object_list": self.crud_class._get_queryset(),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _auto_detect_fields(model):
    """Return reasonable fields for a model, excluding auto/system fields."""
    skip_types = (AutoField, BigAutoField)
    fields = []
    for f in model._meta.get_fields():
        if not isinstance(f, (Field, ForeignKey)):
            continue  # skip reverse relations, M2M
        if isinstance(f, skip_types):
            continue
        if f.name == "password":
            continue
        if not getattr(f, "editable", True):
            continue
        fields.append(f.name)
    return fields


def _resolve_fields_from_admin(model, modeladmin):
    """Extract usable field names from a ModelAdmin's list_display."""
    model_field_names = {f.name for f in model._meta.get_fields()}
    fields = []
    for entry in modeladmin.list_display:
        if entry in model_field_names and entry != "pk":
            fields.append(entry)
        # Skip callables, __str__, and non-field entries
    return fields or _auto_detect_fields(model)


def _resolve_readonly_from_admin(modeladmin):
    """Check if admin treats the model as readonly via permission overrides."""
    from django.test import RequestFactory

    cls = type(modeladmin)
    if "has_change_permission" in cls.__dict__ or "has_add_permission" in cls.__dict__:
        try:
            fake_request = RequestFactory().get("/")
            if not modeladmin.has_change_permission(fake_request) or not modeladmin.has_add_permission(fake_request):
                return True
        except Exception:
            pass
    return False


def _resolve_group(model, modeladmin):
    """Determine the display group for a model."""
    group = getattr(modeladmin, "explorer_group", None)
    if group:
        return group
    return model._meta.app_label.replace("_", " ").title()


def _build_auto_table(
    model: type[models.Model],
    list_fields: list[str],
    url_base: str,
    actions: list[Action],
    namespace: str | None = None,
) -> type[tables.Table]:
    """Auto-generate a django-tables2 Table class with sortable columns.

    The first field becomes a DetailLinkColumn (if DETAIL action exists),
    and an ActionsColumn is appended (if UPDATE or DELETE exist).
    """
    has_detail = Action.DETAIL in actions
    has_update = Action.UPDATE in actions
    has_delete = Action.DELETE in actions

    link_field = list_fields[0] if list_fields else None
    attrs = {}

    for field_name in list_fields:
        if field_name == link_field and has_detail:
            attrs[field_name] = DetailLinkColumn(url_base=url_base, namespace=namespace)
        else:
            attrs[field_name] = tables.Column()

    if has_update or has_delete:
        attrs["actions"] = ActionsColumn(url_base=url_base, edit=has_update, delete=has_delete, namespace=namespace)

    meta_attrs = {
        "model": model,
        "fields": list(list_fields),
        "attrs": {"class": "crud-table"},
    }
    attrs["Meta"] = type("Meta", (), meta_attrs)

    return type(f"Explorer{model.__name__}Table", (tables.Table,), attrs)


# ---------------------------------------------------------------------------
# Explorer Site (registry)
# ---------------------------------------------------------------------------


class ExplorerSite:
    """Registry that manages model registration and generates CRUDView subclasses.

    Supports explicit registration via register(), autodiscovery of explorer.py
    files, and legacy discovery from admin.site._registry.

    Child sites can inherit from a parent, filtered by groups, with per-instance
    form overrides that don't leak back to the parent:

        estimating = ExplorerSite(
            name="estimating",
            parent=explorer,
            groups=["Construction"],
            display_name="Estimating",
        )
        estimating.set_form(Estimate, EstimateWorkflowForm)
    """

    def __init__(
        self,
        name: str | None = None,
        parent: ExplorerSite | None = None,
        groups: list[str] | None = None,
        display_name: str | None = None,
    ):
        self._name = name
        self._parent = parent
        self._groups = [g.lower() for g in groups] if groups else None
        self._display_name = display_name or (name.replace("_", " ").title() if name else "Explorer")
        self._registry: dict[tuple[type[models.Model], str], type] = {}
        self._crud_classes: list[type[CRUDView]] = []
        self._model_info: list[ModelInfo] = []
        self._form_overrides: dict[type[models.Model], type[forms.ModelForm]] = {}
        self._built = False

    # -- Registration --

    def register(
        self,
        model: type[models.Model],
        admin_class: type | None = None,
        group: str | None = None,
    ) -> None:
        """Register a model with Explorer.

        Args:
            model: Django model class.
            admin_class: ModelAdmin subclass for config. If None, a bare
                         ModelAdmin is used.
            group: Display group name. Defaults to app_label title.
        """
        from django.contrib import admin as django_admin

        if admin_class is None:
            admin_class = django_admin.ModelAdmin
        group_key = group or model._meta.app_label.replace("_", " ").title()
        self._registry[(model, group_key)] = admin_class

    def autodiscover(self) -> None:
        """Import explorer.py from every installed app."""
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("explorer")

    def discover_admin(self) -> None:
        """Legacy: scan admin.site._registry for explorer_enabled=True.

        Only registers models not already in _registry (autodiscover takes precedence).
        """
        from django.conf import settings
        from django.contrib import admin

        discover_all = getattr(settings, "EXPLORER_DISCOVER_ALL", False)
        registered_models = {model for model, _ in self._registry}

        for model, modeladmin in admin.site._registry.items():
            if model in registered_models:
                continue
            if not discover_all and not getattr(modeladmin, "explorer_enabled", False):
                continue
            try:
                group = _resolve_group(model, modeladmin)
                self._registry[(model, group)] = type(modeladmin)
            except Exception:
                logger.warning(
                    "Explorer: skipping %s.%s (discovery error)",
                    model._meta.app_label,
                    model._meta.model_name,
                )

    def set_form(self, model: type[models.Model], form_class: type[forms.ModelForm]) -> None:
        """Set a per-instance form override. Only this site sees this form."""
        self._form_overrides[model] = form_class

    def _inherit_from_parent(self) -> None:
        """Copy filtered entries from parent._registry into own _registry."""
        if not self._parent:
            return
        for (model, group_key), admin_class in self._parent._registry.items():
            if self._groups and group_key.lower() not in self._groups:
                continue
            if (model, group_key) not in self._registry:
                self._registry[(model, group_key)] = admin_class

    @property
    def urls(self) -> tuple[list[URLPattern], str | None]:
        """Return (patterns, app_name) tuple for use with include().

        Usage: path("estimating/", include(estimating.urls, namespace="estimating"))
        """
        return (self.get_url_patterns(), self._name)

    # -- Build phase --

    def build_crud_classes(self) -> None:
        """Create CRUDView subclasses for all registered models.

        For child sites with a parent, inherits from parent first (lazy build).
        """
        if self._parent and not self._built:
            self._inherit_from_parent()

        from django.contrib import admin

        for (model, group_key), admin_class in self._registry.items():
            try:
                self._build_one(model, group_key, admin_class, admin.site)
            except Exception:
                logger.warning(
                    "Explorer: skipping %s.%s (build error)",
                    model._meta.app_label,
                    model._meta.model_name,
                    exc_info=True,
                )
        self._built = True

    def _build_one(self, model, group_key, admin_class, admin_site):
        """Build a single CRUDView subclass and register its ModelInfo."""
        from apps.smallstack.displays import TableDisplay

        group_slug = slugify(group_key)
        model_name = model._meta.model_name

        # Child sites: no "explorer/" prefix — the mount path provides that
        if self._name:
            url_base = f"{group_slug}/{model_name}"
        else:
            url_base = f"explorer/{group_slug}/{model_name}"

        # Instantiate admin for reading instance-level attrs
        admin_instance = admin_class(model, admin_site)

        # Resolve fields
        explorer_fields = getattr(admin_instance, "explorer_fields", None)
        if explorer_fields:
            resolved_fields = list(explorer_fields)
        else:
            resolved_fields = _resolve_fields_from_admin(model, admin_instance)

        # Readonly detection
        readonly = getattr(
            admin_instance,
            "explorer_readonly",
            _resolve_readonly_from_admin(admin_instance),
        )

        if readonly:
            actions = [Action.LIST, Action.DETAIL]
        else:
            actions = list(Action)

        # Split: list_fields can include non-editable fields,
        # but form fields must only contain editable ones.
        editable_names = {
            f.name
            for f in model._meta.get_fields()
            if getattr(f, "editable", False) and not isinstance(f, (AutoField, BigAutoField))
        }
        form_fields = [f for f in resolved_fields if f in editable_names]

        # Auto-generate a django-tables2 Table for sortable columns
        namespace = self._name
        table_class = _build_auto_table(model, resolved_fields, url_base, actions, namespace=namespace)

        # Merge transforms: explorer_preview_fields → "preview", then explicit wins
        preview_fields = getattr(admin_instance, "explorer_preview_fields", [])
        explorer_transforms = getattr(admin_instance, "explorer_field_transforms", {})
        merged_transforms = {}
        for pf in preview_fields:
            merged_transforms[pf] = "preview"
        merged_transforms.update(explorer_transforms)

        paginate_by = getattr(admin_instance, "explorer_paginate_by", 10)

        # Display config: admin class can specify explorer_displays / explorer_detail_displays
        displays = getattr(admin_class, "explorer_displays", [TableDisplay])
        detail_displays = getattr(admin_class, "explorer_detail_displays", [])

        # Form display config
        form_displays = getattr(admin_class, "explorer_form_displays", [])
        create_displays = getattr(admin_class, "explorer_create_displays", [])
        edit_displays = getattr(admin_class, "explorer_edit_displays", [])

        # Form class: per-instance override wins, then admin's explorer_form_class
        form_class = self._form_overrides.get(model)
        if form_class is None:
            form_class = getattr(admin_instance, "explorer_form_class", None)

        # Breadcrumb parent: child sites use their own display name + namespaced index
        if self._name:
            breadcrumb_parent = (self._display_name, f"{self._name}:index")
            class_name_prefix = f"{self._name.title().replace('_', '')}"
        else:
            breadcrumb_parent = ("Explorer", "explorer-index")
            class_name_prefix = "Explorer"

        crud_cls = type(
            f"{class_name_prefix}{model.__name__}CRUDView",
            (CRUDView,),
            {
                "model": model,
                "admin_class": admin_class,
                "fields": form_fields or resolved_fields,
                "list_fields": resolved_fields,
                "url_base": url_base,
                "namespace": namespace,
                "paginate_by": paginate_by,
                "table_class": table_class,
                "mixins": [StaffRequiredMixin],
                "actions": actions,
                "displays": displays,
                "detail_displays": detail_displays,
                "form_displays": form_displays,
                "create_displays": create_displays,
                "edit_displays": edit_displays,
                "form_class": form_class,
                "preview_fields": preview_fields,
                "field_transforms": merged_transforms,
                "breadcrumb_parent": breadcrumb_parent,
                "enable_api": getattr(admin_class, "explorer_enable_api", False),
                "export_formats": list(getattr(admin_class, "explorer_export_formats", [])),
                "api_extra_fields": list(getattr(admin_class, "explorer_api_extra_fields", [])),
                "api_expand_fields": list(getattr(admin_class, "explorer_api_expand_fields", [])),
                "api_aggregate_fields": list(getattr(admin_class, "explorer_api_aggregate_fields", [])),
            },
        )

        self._crud_classes.append(crud_cls)
        self._model_info.append(
            ModelInfo(
                app_label=model._meta.app_label,
                model_name=model_name,
                verbose_name=str(model._meta.verbose_name).capitalize(),
                verbose_name_plural=str(model._meta.verbose_name_plural).capitalize(),
                model_class=model,
                url_base=url_base,
                readonly=readonly,
                group=group_key,
                namespace=namespace,
            )
        )

    # -- Public API: raw data --

    def get_url_patterns(self) -> list[URLPattern]:
        # Lazy build: child sites build on first URL pattern request
        if self._parent and not self._built:
            self.build_crud_classes()
        patterns = []
        for crud_cls in self._crud_classes:
            patterns.extend(crud_cls.get_urls())
        # Child sites: add an index redirect to the first model's list view
        if self._name and self._model_info:
            first_list_url_name = f"{self._name}:{self._model_info[0].url_base}-list"

            def _index_redirect(request, _url=first_list_url_name):
                from django.shortcuts import redirect

                return redirect(reverse(_url))

            patterns.append(path("", _index_redirect, name="index"))
        return patterns

    def get_models(self) -> list[ModelInfo]:
        return self._model_info

    def get_grouped_models(self) -> dict[str, list[ModelInfo]]:
        """Return models organized by group, preserving discovery order."""
        groups: dict[str, list[ModelInfo]] = {}
        for info in self._model_info:
            if info.group not in groups:
                groups[info.group] = []
            groups[info.group].append(info)
        return groups

    # -- Public API: context helpers --

    def get_group_context(self, group_name: str) -> GroupContext | None:
        """Return everything a group page template needs, or None if not found.

        Usage in a view:
            ctx = explorer.get_group_context("Monitoring")
        """
        grouped = self.get_grouped_models()

        # Case-insensitive match
        matched = None
        for name in grouped:
            if name.lower() == group_name.lower():
                matched = name
                break
        if not matched:
            return None

        models = [info.with_counts() for info in grouped[matched]]
        all_groups = sorted(grouped.keys())

        return GroupContext(
            group_name=matched,
            models=models,
            all_groups=all_groups,
        )

    def get_apps(self) -> list[str]:
        """Return sorted list of unique app_labels across all registered models."""
        return sorted({info.app_label for info in self._model_info})

    def get_app_context(self, app_label: str) -> AppContext | None:
        """Return everything an app page template needs, or None if not found.

        Usage in a view:
            ctx = explorer.get_app_context("heartbeat")
        """
        models = [info for info in self._model_info if info.app_label == app_label]
        if not models:
            return None

        return AppContext(
            app_label=app_label,
            app_verbose_name=app_label.replace("_", " ").title(),
            models=[info.with_counts() for info in models],
            all_apps=self.get_apps(),
        )

    def get_model_context(self, app_label: str, model_name: str) -> ModelContext | None:
        """Return everything a single-model page template needs, or None if not found.

        Usage in a view:
            ctx = explorer.get_model_context("heartbeat", "heartbeat")
        """
        # Find the model info
        info = None
        for m in self._model_info:
            if m.app_label == app_label and m.model_name == model_name:
                info = m
                break
        if not info:
            return None

        # Find the matching CRUD class
        crud_cls = None
        for cls in self._crud_classes:
            if cls._get_url_base() == info.url_base:
                crud_cls = cls
                break
        if not crud_cls:
            return None

        url_base = crud_cls._get_url_base()
        create_url = None
        if Action.CREATE in crud_cls.actions:
            create_url = crud_cls._reverse(f"{url_base}-create")

        return ModelContext(
            info=info.with_counts(),
            crud_class=crud_cls,
            object_verbose_name=str(crud_cls.model._meta.verbose_name).capitalize(),
            object_verbose_name_plural=str(crud_cls.model._meta.verbose_name_plural).capitalize(),
            url_base=url_base,
            list_fields=crud_cls._get_list_fields(),
            detail_fields=crud_cls._get_detail_fields(),
            link_field=crud_cls._get_link_field(),
            crud_actions=crud_cls.actions,
            field_transforms=crud_cls._get_effective_transforms(),
            field_formatters=crud_cls.field_formatters,
            preview_fields=crud_cls.preview_fields,
            create_view_url=create_url,
        )


# Module-level singleton — root site (no name, no parent)
explorer = ExplorerSite()

# Backward compat alias — existing code importing explorer_registry still works
explorer_registry = explorer
