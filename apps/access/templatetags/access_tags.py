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
