"""Template tags for SmallStack CRUD views."""

import datetime

from django import template
from django.urls import reverse
from django.utils.safestring import mark_safe

register = template.Library()


def _get_field_value(obj, field_name, field_formatters, context=None):
    """Extract and format a field value from an object."""
    value = getattr(obj, field_name, "")

    # Use get_FOO_display() for choice fields
    display_method = getattr(obj, f"get_{field_name}_display", None)
    if display_method:
        value = display_method()
    # Friendly boolean display
    elif isinstance(value, bool):
        value = "\u2713" if value else "\u2014"
    elif value is None:
        value = "\u2014"
    # Datetime fields: use localtime_tooltip for TZ-aware display
    elif isinstance(value, datetime.datetime) and context is not None:
        from .theme_tags import localtime_tooltip

        value = mark_safe(localtime_tooltip(context, value, force_tooltip=True))

    # Apply custom formatter
    if field_name in field_formatters:
        value = field_formatters[field_name](value, obj)

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
    crud_actions, field_formatters.
    """
    from apps.smallstack.crud import Action

    object_list = context.get("object_list", [])
    list_fields = context.get("list_fields", [])
    link_field = context.get("link_field")
    url_base = context.get("url_base", "")
    crud_actions = context.get("crud_actions", [])
    field_formatters = context.get("field_formatters", {})

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
            value = _get_field_value(obj, field_name, field_formatters, context)
            cells.append(
                {
                    "value": value,
                    "is_link": field_name == link_field and has_detail,
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

    Expects in context: object, detail_fields, field_formatters.
    """
    obj = context.get("object")
    detail_fields = context.get("detail_fields", [])
    field_formatters = context.get("field_formatters", {})

    rows = []
    if obj:
        model = obj.__class__
        for field_name in detail_fields:
            label = _get_field_label(model, field_name)
            value = _get_field_value(obj, field_name, field_formatters, context)
            rows.append({"label": label, "value": value})

    return {"detail_rows": rows}
