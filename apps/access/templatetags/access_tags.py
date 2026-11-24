"""Small helpers for the Access templates."""

from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.filter
def get_item(mapping: Any, key: Any) -> Any:
    """``{{ row|get_item:column }}``: a dict value by a key held in a variable
    (an evidence sheet's rows are dicts keyed by its column names)."""
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def column_label(key: Any) -> str:
    """``last_granted_by`` → ``last granted by``: an evidence column's key as
    a heading (the CSV keeps the key)."""
    return str(key).replace("_", " ")


@register.filter
def is_long(value: Any) -> bool:
    """Whether a cell's text should wrap (a note, a joined list) rather than
    keep its line; short values and timestamps stay on one line."""
    return len(str(value or "")) > 40
