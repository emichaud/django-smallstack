"""Helpers for full-page (non-HTMX) sortable table headers.

Used by list pages that render a hand-rolled table from a Python list
(rather than the CRUDView/HTMX flow) and want django-tables2-style clickable
column headers — e.g. the Explorer classic index and the Timezone dashboard.

Pair with ``{% querystring ordering=h.next_ordering %}`` in the template so the
sort link preserves any other query params (search ``q``, filters, …).
"""

from typing import Any


def build_sort_headers(columns: list[tuple[str, str]], ordering: str) -> list[dict[str, Any]]:
    """Build header metadata for clickable sort columns.

    Args:
        columns: ``[(key, label), …]`` in display order.
        ordering: the current ``?ordering=`` value (``"key"`` asc, ``"-key"`` desc).

    Returns a list of dicts with ``key``, ``label``, ``direction``
    (``"asc"``/``"desc"``/``None``), and ``next_ordering`` — the value to put in
    the column's sort link. Clicking toggles asc → desc → asc (two-state), the
    same behaviour as the HTMX ``{% sortable_th %}`` tag.
    """
    current = ordering.lstrip("-")
    current_desc = ordering.startswith("-")
    headers = []
    for key, label in columns:
        direction = None
        next_ordering = key  # first click → ascending
        if key == current:
            direction = "desc" if current_desc else "asc"
            # asc → desc; desc → back to asc
            next_ordering = key if current_desc else f"-{key}"
        headers.append(
            {
                "key": key,
                "label": label,
                "direction": direction,
                "next_ordering": next_ordering,
            }
        )
    return headers
