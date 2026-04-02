"""Template tags for SmallStack CRUD views."""

import datetime
import json

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

from apps.smallstack.crud import _resolve_transform_spec
from apps.smallstack.transforms import TRUNCATE_THRESHOLD

register = template.Library()


def _get_field_value(obj, field_name, field_transforms, context=None, is_link_field=False):
    """Extract and format a field value from an object.

    Args:
        obj: The model instance.
        field_name: Name of the field to render.
        field_transforms: Dict of {field_name: transform_spec} from CRUDView.
        context: Template context (needed for timezone rendering).
        is_link_field: Whether this field is the clickable link column.
    """
    value = getattr(obj, field_name, "")

    # JSONField returns dicts/lists — serialize to string for display
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)

    # Use get_FOO_display() for choice fields
    display_method = getattr(obj, f"get_{field_name}_display", None)
    if display_method:
        value = display_method()
    # Friendly boolean display
    elif isinstance(value, bool):
        value = "\u2713" if value else "\u2014"
    elif value is None:
        value = "\u2014"
    # Auto-apply localtime for datetime fields when no explicit transform is set
    elif isinstance(value, datetime.datetime) and context is not None:
        if field_name not in field_transforms:
            from .theme_tags import localtime_tooltip

            value = mark_safe(localtime_tooltip(context, value, force_tooltip=True))

    # Apply transform (or legacy callable)
    spec = field_transforms.get(field_name)
    if spec is not None:
        transform, options = _resolve_transform_spec(spec)
        if transform is not None:
            if callable(transform) and not hasattr(transform, "inline"):
                # Legacy field_formatters callable: (value, obj) → str
                value = transform(value, obj)
            else:
                # Pass real template context directly — transforms can
                # access any context var they need (url_base, request, etc.)
                opts = {**options, "is_link_field": True} if is_link_field else options
                value = transform.inline(value, obj, field_name, context, **opts)

    return value


def _get_field_label(model, field_name):
    """Get the verbose_name for a model field, with fallback."""
    try:
        field = model._meta.get_field(field_name)
        return str(field.verbose_name).capitalize()
    except Exception:
        return field_name.replace("_", " ").capitalize()


def _ns_reverse(url_name: str, namespace: str | None = None, **kwargs) -> str:
    """Reverse a URL name, prepending namespace if set."""
    if namespace:
        return reverse(f"{namespace}:{url_name}", **kwargs)
    return reverse(url_name, **kwargs)


def _build_sort_headers(list_fields, model, request, column_widths=None):
    """Build header metadata with sort state for each column.

    Returns a list of dicts with keys: label, field_name, sortable,
    direction (asc/desc/None), next_ordering (the ?ordering= value to toggle to),
    width (optional CSS width from column_widths).
    """
    current_ordering = request.GET.get("ordering", "").strip() if request else ""
    current_field = current_ordering.lstrip("-")
    current_dir = None
    if current_ordering.startswith("-") and current_field:
        current_dir = "desc"
    elif current_field:
        current_dir = "asc"

    # Determine which fields are sortable (must be real model fields)
    model_field_names = {f.name for f in model._meta.get_fields()} if model else set()

    headers = []
    for field_name in list_fields:
        label = _get_field_label(model, field_name) if model else field_name.replace("_", " ").capitalize()
        sortable = field_name in model_field_names

        direction = None
        next_ordering = field_name  # default: first click → ascending
        if sortable and field_name == current_field:
            direction = current_dir
            if current_dir == "asc":
                next_ordering = f"-{field_name}"
            else:
                # desc → back to asc (two-state toggle)
                next_ordering = field_name

        header = {
            "label": label,
            "field_name": field_name,
            "sortable": sortable,
            "direction": direction,
            "next_ordering": next_ordering,
        }
        if column_widths and field_name in column_widths:
            header["width"] = column_widths[field_name]
        headers.append(header)
    return headers


@register.inclusion_tag("smallstack/crud/includes/table.html", takes_context=True)
def crud_table(context):
    """Render a CRUD list table from context variables.

    Expects in context: object_list, list_fields, link_field, url_base,
    crud_actions, field_transforms.
    """
    from apps.smallstack.crud import Action

    object_list = context.get("object_list", [])
    list_fields = context.get("list_fields", [])
    link_field = context.get("link_field")
    url_base = context.get("url_base", "")
    crud_actions = context.get("crud_actions", [])
    field_transforms = context.get("field_transforms", {})
    url_namespace = context.get("url_namespace")
    request = context.get("request")
    enable_bulk = context.get("enable_bulk", False)

    # Resolve model from first object or from context
    model = object_list[0].__class__ if object_list else None

    # Build sortable headers
    crud_config = context.get("crud_config")
    column_widths = getattr(crud_config, "column_widths", None) if crud_config else None
    headers = _build_sort_headers(list_fields, model, request, column_widths=column_widths)

    has_detail = Action.DETAIL in crud_actions
    has_update = Action.UPDATE in crud_actions
    has_delete = Action.DELETE in crud_actions
    show_actions = has_update or has_delete

    # Build rows
    rows = []
    for obj in object_list:
        cells = []
        for field_name in list_fields:
            is_link = field_name == link_field and has_detail
            # Raw value for title tooltip (before transforms add HTML)
            raw = getattr(obj, field_name, "")
            if isinstance(raw, (dict, list)):
                title = json.dumps(raw, ensure_ascii=False)
            elif raw is None:
                title = ""
            else:
                display_method = getattr(obj, f"get_{field_name}_display", None)
                title = str(display_method()) if display_method else str(raw)
            value = _get_field_value(
                obj,
                field_name,
                field_transforms,
                context,
                is_link_field=is_link,
            )
            cells.append(
                {
                    "value": value,
                    "is_link": is_link,
                    "title": title,
                }
            )

        detail_url = _ns_reverse(f"{url_base}-detail", url_namespace, kwargs={"pk": obj.pk}) if has_detail else None

        actions = []
        if has_update:
            actions.append(
                {
                    "url": _ns_reverse(f"{url_base}-update", url_namespace, kwargs={"pk": obj.pk}),
                    "label": "Edit",
                }
            )
        if has_delete:
            actions.append(
                {
                    "url": _ns_reverse(f"{url_base}-delete", url_namespace, kwargs={"pk": obj.pk}),
                    "label": "Delete",
                    "is_delete": True,
                }
            )

        rows.append(
            {
                "pk": obj.pk,
                "cells": cells,
                "detail_url": detail_url,
                "actions": actions,
                "obj_name": str(obj),
            }
        )

    return {
        "headers": headers,
        "rows": rows,
        "show_actions": show_actions,
        "enable_bulk": enable_bulk,
    }


@register.inclusion_tag("smallstack/crud/includes/sortable_th.html", takes_context=True)
def sortable_th(context, field_name, label, target="#tab-content", include_selector=""):
    """Render a sortable <th> header for manual tables.

    Usage in templates:
        {% load crud_tags %}
        {% sortable_th "timestamp" "Time" target="#tab-content" %}

    Reads ?ordering= from the current request to show sort direction.
    Clicking toggles asc ↔ desc (two-state).
    """
    request = context.get("request")
    current_ordering = request.GET.get("ordering", "").strip() if request else ""
    current_field = current_ordering.lstrip("-")

    direction = None
    next_ordering = field_name
    if field_name == current_field:
        if current_ordering.startswith("-"):
            direction = "desc"
            next_ordering = field_name  # back to asc
        else:
            direction = "asc"
            next_ordering = f"-{field_name}"

    # Build the URL preserving existing query params
    params = request.GET.copy() if request else {}
    params["ordering"] = next_ordering

    return {
        "label": label,
        "direction": direction,
        "next_ordering": next_ordering,
        "hx_target": target,
        "hx_include": include_selector,
        "query_string": params.urlencode(),
    }


@register.simple_tag(takes_context=True)
def field_preview_url(context, url_base, obj, field_name):
    """Return the URL for a field preview endpoint.

    Usage: {% field_preview_url url_base obj "field_name" %}
    """
    return _ns_reverse(
        f"{url_base}-field-preview",
        context.get("url_namespace"),
        kwargs={"pk": obj.pk, "field_name": field_name},
    )


@register.inclusion_tag("smallstack/crud/includes/field_preview.html")
def field_preview(url_base, obj, field_name, threshold=None):
    """Render a truncated field value with click-to-preview trigger.

    Usage in any template:
        {% load crud_tags %}
        {% field_preview url_base obj "bio" %}
        {% field_preview url_base obj "notes" threshold=100 %}

    Like {% localtime_tooltip %} — a transformation tag you apply selectively.
    """
    threshold = threshold or TRUNCATE_THRESHOLD
    raw_value = getattr(obj, field_name, "")

    if isinstance(raw_value, (dict, list)):
        text = json.dumps(raw_value, ensure_ascii=False)
    elif raw_value is None:
        text = ""
    else:
        text = str(raw_value)

    needs_truncation = len(text) > threshold
    truncated = text[:threshold].rstrip() if needs_truncation else text

    preview_url = _ns_reverse(
        f"{url_base}-field-preview",
        namespace=None,
        kwargs={"pk": obj.pk, "field_name": field_name},
    )

    return {
        "text": truncated,
        "needs_truncation": needs_truncation,
        "preview_url": preview_url,
    }


@register.simple_tag(takes_context=True)
def field_transform(context, obj, field_name, transform_name, url_base=None, **options):
    """Apply a named transform to a field for standalone use in templates.

    Usage:
        {% load crud_tags %}
        {% field_transform obj "bio" "preview" %}
        {% field_transform obj "bio" "preview" threshold=100 %}
        {% field_transform obj "bio" "preview" url_base="manage/tickets" %}
    """
    if url_base is not None:
        context = context.new({"url_base": url_base})
    field_transforms = {field_name: (transform_name, options) if options else transform_name}
    return _get_field_value(obj, field_name, field_transforms, context)


@register.filter
def ns(base_name, namespace):
    """Build the correct Explorer URL name for the current site context.

    In custom CRUD templates that may be rendered by either the root Explorer
    or a namespaced child site, use this instead of hardcoding URL names::

        {% load crud_tags %}
        {% url "construction/client-list"|ns:url_namespace %}

    Root explorer (url_namespace is None/empty): prepends ``explorer/``
    → ``explorer/construction/client-list``

    Child site (url_namespace is e.g. ``"estimating"``): prepends namespace
    → ``estimating:construction/client-list``
    """
    if namespace:
        return f"{namespace}:{base_name}"
    return f"explorer/{base_name}"


@register.inclusion_tag("smallstack/crud/includes/form.html", takes_context=True)
def crud_form(context):
    """Render a styled CRUD form from context.

    Usage in templates:
        {% crud_form %}           — renders all fields with SmallStack styling

    Expects in context: form.
    """
    return {"form": context.get("form")}


@register.inclusion_tag("smallstack/crud/includes/detail_table.html", takes_context=True)
def crud_detail(context):
    """Render a CRUD detail table from context variables.

    Expects in context: object, detail_fields, field_transforms.
    """
    obj = context.get("object")
    detail_fields = context.get("detail_fields", [])
    field_transforms = context.get("field_transforms", {})

    rows = []
    if obj:
        model = obj.__class__
        for field_name in detail_fields:
            label = _get_field_label(model, field_name)
            value = _get_field_value(obj, field_name, field_transforms, context)
            rows.append({"label": label, "value": value})

    return {"detail_rows": rows}
