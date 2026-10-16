"""Bucketed-grouping grammar for datasets (R8).

The three core functions (``_dimension_values``, ``_bucket_cond``,
``_derive_buckets``) plus ``AUTO_BUCKET_LIMIT`` are lifted **verbatim** from
call_stats ``apps/reporter/query.py`` (the downstream that proved the grammar).
They are model-agnostic — a queryset + field-name strings + bucket dicts — so a
dataset's bucketed ``series()``/``rows()`` and call_stats's reporter share one
implementation. Do not fork the grammar; extend it here for both consumers.

A *dimension* is a dict::

    {"field": <col>, "buckets": [<bucket>, ...]}          # hand-authored
    {"field": <col>, "auto": true | {"limit": N, "label_field": <col>}}

where each ``<bucket>`` is one of::

    {key, label, lo, hi}          # numeric [lo, hi); hi None ⇒ open-ended
    {key, label, value}           # categorical: field == value
    {key, label, values: [...]}   # categorical IN-group
    {key, label, other: true}     # complement of the sibling buckets' values
"""

from __future__ import annotations

from typing import Any, Optional

from django.db.models import Count, Max, Q, QuerySet

# --- lifted verbatim from call_stats apps/reporter/query.py -----------------


def _dimension_values(buckets: list[dict]) -> list:
    """Every explicit value claimed by a dimension's CATEGORICAL buckets —
    what the `other` catch-all bucket is the complement of."""
    values = []
    for b in buckets:
        if "value" in b:
            values.append(b["value"])
        elif "values" in b:
            values.extend(b["values"])
    return values


def _bucket_cond(field: str, b: dict, dimension_values: list | None = None) -> Q:
    """One bucket's row condition. Three bucket shapes:

    - numeric: {lo, hi}   → [lo, hi); hi None ⇒ open-ended (outlier bucket)
    - categorical: {value} → field == value, or {values: [...]} → field IN
      (grouping several raw values into one bucket, e.g. Phone + Voice Mail)
    - catch-all: {other: true} → NOT IN every value the sibling buckets claim
      (`dimension_values`) — the honest remainder, so a categorical dimension
      never silently drops rows whose value isn't listed
    """
    if b.get("other"):
        return ~Q(**{f"{field}__in": dimension_values or []})
    if "value" in b:
        return Q(**{field: b["value"]})
    if "values" in b:
        return Q(**{f"{field}__in": b["values"]})
    cond = Q(**{f"{field}__gte": b["lo"]})
    if b.get("hi") is not None:
        cond &= Q(**{f"{field}__lt": b["hi"]})
    return cond


# The default cap on auto-derived buckets — enough categories for a readable
# donut/bar; anything past it lands in the appended `other` catch-all.
AUTO_BUCKET_LIMIT = 12


def _derive_buckets(scope_qs: QuerySet[Any], dimension: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize an AUTO categorical dimension ({field, auto: true | {limit,
    label_field}}) into concrete value buckets: one per distinct value of the
    field, ordered by row count (desc, then value for determinism), capped at
    auto.limit (default AUTO_BUCKET_LIMIT) with an `other` catch-all appended
    only when values overflow the cap — the same no-silent-truncation rule as
    hand-authored categorical dimensions.

    Keys derive from the value ("v:<value>") so a chart's buckets and a later
    records()/publish resolve identically without shipping the derived list
    around. Labels come from auto.label_field (e.g. queue_name, one per value
    via Max) or the value itself. MUST be derived from the query's FULL scope
    — never a window/selector-narrowed queryset — so bucket keys stay stable
    across windows, subscribed slices, and the aggregate↔records pair."""
    auto = dimension.get("auto")
    opts: dict = auto if isinstance(auto, dict) else {}
    limit = int(opts.get("limit") or AUTO_BUCKET_LIMIT)
    field = dimension["field"]
    label_field = opts.get("label_field")

    rows_qs = scope_qs.values(field).annotate(_n=Count("id"))
    if label_field:
        rows_qs = rows_qs.annotate(_label=Max(label_field))
    rows = list(rows_qs.order_by("-_n", field)[: limit + 1])
    overflow = len(rows) > limit

    buckets = []
    for r in rows[:limit]:
        value = r[field]
        fallback = "(blank)" if value in (None, "") else str(value)
        buckets.append(
            {"key": f"v:{value}", "label": str(r.get("_label") or fallback), "value": value}
        )
    if overflow:
        buckets.append({"key": "other", "label": "Other", "other": True})
    return buckets


# --- dataset-side helpers ---------------------------------------------------


def resolve_buckets(ds: Any, dimension: dict, request: Any) -> list[dict]:
    """Concrete bucket list for a dimension dict.

    An ``auto`` dimension is materialized against the dataset's **unnarrowed**
    base queryset (``ds.queryset(request, {})`` — the R4 seam), so derived keys
    stay identical whether or not runtime filters are applied (contract point 4):
    a filtered series returns the same buckets, just zero-counted where empty.
    """
    if dimension.get("auto"):
        return _derive_buckets(ds.queryset(request, {}), dimension)
    return list(dimension.get("buckets") or [])


def bucket_by_key(buckets: list[dict], key: str) -> Optional[dict]:
    return next((b for b in buckets if b.get("key") == key), None)
