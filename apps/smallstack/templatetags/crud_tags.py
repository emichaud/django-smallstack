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

    # Resolve model from first object or from context
    model = object_list[0].__class__ if object_list else None

    # Build headers
    headers = []
    for field_name in list_fields:
        if model:
            headers.append(_get_field_label(model, field_name))
        else:
            headers.append(field_name.replace("_", " ").capitalize())

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
            value = _get_field_value(
                obj, field_name, field_transforms, context,
                is_link_field=is_link,
            )
            cells.append(
                {
                    "value": value,
                    "is_link": is_link,
                }
            )

        detail_url = reverse(f"{url_base}-detail", kwargs={"pk": obj.pk}) if has_detail else None

        actions = []
        if has_update:
            actions.append(
                {
                    "url": reverse(f"{url_base}-update", kwargs={"pk": obj.pk}),
                    "label": "Edit",
                }
            )
        if has_delete:
            actions.append(
                {
                    "url": reverse(f"{url_base}-delete", kwargs={"pk": obj.pk}),
                    "label": "Delete",
                    "is_delete": True,
                }
            )

        rows.append(
            {
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
    }


@register.simple_tag
def field_preview_url(url_base, obj, field_name):
    """Return the URL for a field preview endpoint.

    Usage: {% field_preview_url url_base obj "field_name" %}
    """
    return reverse(
        f"{url_base}-field-preview",
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

    preview_url = reverse(
        f"{url_base}-field-preview",
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
