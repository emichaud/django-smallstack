"""Explorer registry — dynamically creates CRUDView subclasses for admin-registered models."""

from django.db.models import AutoField, BigAutoField, Field, ForeignKey

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin


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


class ExplorerRegistry:
    def __init__(self):
        self._configs = []  # list of (model, fields, readonly, group)
        self._crud_classes = []  # built CRUDView subclasses
        self._model_info = []  # metadata for index view

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
                self._configs.append((model, fields, readonly, group))
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "Explorer: skipping %s.%s (discovery error)",
                    model._meta.app_label,
                    model._meta.model_name,
                )

    def build(self):
        for model, fields, readonly, group in self._configs:
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

            crud_cls = type(
                f"Explorer{model.__name__}CRUDView",
                (CRUDView,),
                {
                    "model": model,
                    "fields": form_fields or resolved_fields,
                    "list_fields": resolved_fields,
                    "url_base": url_base,
                    "paginate_by": 25,
                    "mixins": [StaffRequiredMixin],
                    "actions": actions,
                    "breadcrumb_parent": ("Explorer", "explorer-index"),
                },
            )

            self._crud_classes.append(crud_cls)
            self._model_info.append(
                {
                    "app_label": app_label,
                    "model_name": model_name,
                    "verbose_name": str(model._meta.verbose_name).capitalize(),
                    "verbose_name_plural": str(model._meta.verbose_name_plural).capitalize(),
                    "model_class": model,
                    "url_base": url_base,
                    "readonly": readonly,
                    "group": group,
                }
            )

    def get_url_patterns(self):
        patterns = []
        for crud_cls in self._crud_classes:
            patterns.extend(crud_cls.get_urls())
        return patterns

    def get_models(self):
        return self._model_info

    def get_grouped_models(self):
        """Return models organized by group, preserving discovery order."""
        groups = {}
        for info in self._model_info:
            group = info["group"]
            if group not in groups:
                groups[group] = []
            groups[group].append(info)
        return groups


explorer_registry = ExplorerRegistry()
