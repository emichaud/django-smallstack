"""Dataset capabilities — what a component may ask of a dataset before binding.

A **capability** is a shape guarantee derived from a dataset's ``schema()``:
"I have a measure you can aggregate", "I have a date column a period can
narrow". A builder (or an agent) reads them to decide which components are
even offerable — a grouped stat needs a dimension, a period-aware metric needs
a date — and to explain why the rest are greyed out, before fetching a row.

DB-free: it reads an already-computed ``schema()`` dict. Ported from
call_stats ``apps/datasets/capabilities.py``.
"""

from __future__ import annotations

from typing import Any, Iterable

MEASURE = "measure"  # ≥1 numeric column to aggregate (sum/avg/min/max)
DIMENSION = "dimension"  # ≥1 non-numeric column to group by (a grouped stat)
DIMENSION2 = "dimension2"  # ≥2 dimensions — enough to cross-tabulate
DATE = "date"  # ≥1 date/datetime column (period filters, time grains)

VOCABULARY = frozenset({MEASURE, DIMENSION, DIMENSION2, DATE})

_DATE_TYPES = frozenset({"date", "datetime"})

#: Plain-language reasons, ready for a tooltip ("needs a date column").
REASONS = {
    MEASURE: "needs a numeric column",
    DIMENSION: "needs a column to group by",
    DIMENSION2: "needs two columns to group by",
    DATE: "needs a date column",
}


def capabilities(schema: dict[str, Any]) -> frozenset[str]:
    """The capability set a dataset advertises, from its ``schema()``."""
    caps: set[str] = set()
    dimensions = 0
    for col in schema.get("columns", []):
        if col.get("role") == "measure":
            caps.add(MEASURE)
        elif col.get("role") == "dimension":
            caps.add(DIMENSION)
            dimensions += 1
        if col.get("type") in _DATE_TYPES:
            caps.add(DATE)
    if dimensions >= 2:
        caps.add(DIMENSION2)
    return frozenset(caps)


def missing_for(required: Iterable[str], caps: Iterable[str]) -> frozenset[str]:
    """Which *required* capabilities *caps* does NOT satisfy (empty ⇒ offerable)."""
    return frozenset(required) - frozenset(caps)
