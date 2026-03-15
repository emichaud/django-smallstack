"""Explorer registry — dynamically creates CRUDView subclasses for admin-registered models."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import django_tables2 as tables
from django.db.models import AutoField, BigAutoField, Field, ForeignKey
from django.urls import reverse

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.tables import ActionsColumn, DetailLinkColumn

if TYPE_CHECKING:
    from django.db import models


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
            count=self.model_class.objects.count(),
            list_url=reverse(f"{self.url_base}-list"),
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


def _build_auto_table(model, list_fields, url_base, actions):
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
            attrs[field_name] = DetailLinkColumn(url_base=url_base)
        else:
            attrs[field_name] = tables.Column()

    if has_update or has_delete:
        attrs["actions"] = ActionsColumn(
            url_base=url_base, edit=has_update, delete=has_delete
        )

    meta_attrs = {
        "model": model,
        "fields": list(list_fields),
        "attrs": {"class": "crud-table"},
    }
    attrs["Meta"] = type("Meta", (), meta_attrs)

    return type(f"Explorer{model.__name__}Table", (tables.Table,), attrs)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ExplorerRegistry:
    def __init__(self):
        self._configs = []  # list of (model, fields, readonly, group)
        self._crud_classes = []  # built CRUDView subclasses
        self._model_info: list[ModelInfo] = []

    def discover(self):
        """Walk admin.site._registry and collect models with explorer_enabled=True."""
        from django.conf import settings
        from django.contrib import admin

        discover_all = getattr(settings, "EXPLORER_DISCOVER_ALL", False)

        for model, modeladmin in admin.site._registry.items():
            if not discover_all and not getattr(modeladmin, "explorer_enabled", False):
                continue
            try:
                fields = getattr(modeladmin, "explorer_fields", None)
                if not fields:
                    fields = _resolve_fields_from_admin(model, modeladmin)
                readonly = getattr(modeladmin, "explorer_readonly", _resolve_readonly_from_admin(modeladmin))
                group = _resolve_group(model, modeladmin)
                preview_fields = getattr(modeladmin, "explorer_preview_fields", [])
                explorer_transforms = getattr(modeladmin, "explorer_field_transforms", {})

                # Merge: explorer_preview_fields → "preview" transform, then explicit wins
                merged_transforms = {}
                for pf in preview_fields:
                    merged_transforms[pf] = "preview"
                merged_transforms.update(explorer_transforms)

                paginate_by = getattr(modeladmin, "explorer_paginate_by", 10)

                self._configs.append((model, fields, readonly, group, preview_fields, merged_transforms, paginate_by))
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Explorer: skipping %s.%s (discovery error)",
                    model._meta.app_label,
                    model._meta.model_name,
                )

    def build(self):
        for model, fields, readonly, group, preview_fields, field_transforms, paginate_by in self._configs:
            resolved_fields = fields or _auto_detect_fields(model)
            app_label = model._meta.app_label
            model_name = model._meta.model_name
            url_base = f"explorer/{app_label}/{model_name}"

            if readonly:
                actions = [Action.LIST, Action.DETAIL]
            else:
                actions = list(Action)

            # Split: list_fields can include non-editable fields,
            # but form fields must only contain editable ones.
            editable_names = {
                f.name for f in model._meta.get_fields()
                if getattr(f, "editable", False) and not isinstance(f, (AutoField, BigAutoField))
            }
            form_fields = [f for f in resolved_fields if f in editable_names]

            # Auto-generate a django-tables2 Table for sortable columns
            table_class = _build_auto_table(model, resolved_fields, url_base, actions)

            crud_cls = type(
                f"Explorer{model.__name__}CRUDView",
                (CRUDView,),
                {
                    "model": model,
                    "fields": form_fields or resolved_fields,
                    "list_fields": resolved_fields,
                    "url_base": url_base,
                    "paginate_by": paginate_by,
                    "table_class": table_class,
                    "mixins": [StaffRequiredMixin],
                    "actions": actions,
                    "preview_fields": preview_fields,
                    "field_transforms": field_transforms,
                    "breadcrumb_parent": ("Explorer", "explorer-index"),
                },
            )

            self._crud_classes.append(crud_cls)
            self._model_info.append(
                ModelInfo(
                    app_label=app_label,
                    model_name=model_name,
                    verbose_name=str(model._meta.verbose_name).capitalize(),
                    verbose_name_plural=str(model._meta.verbose_name_plural).capitalize(),
                    model_class=model,
                    url_base=url_base,
                    readonly=readonly,
                    group=group,
                )
            )

    # -- Public API: raw data --

    def get_url_patterns(self):
        patterns = []
        for crud_cls in self._crud_classes:
            patterns.extend(crud_cls.get_urls())
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
            ctx = explorer_registry.get_group_context("Monitoring")
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
            ctx = explorer_registry.get_app_context("heartbeat")
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
            ctx = explorer_registry.get_model_context("heartbeat", "heartbeat")
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
            create_url = reverse(f"{url_base}-create")

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


explorer_registry = ExplorerRegistry()
