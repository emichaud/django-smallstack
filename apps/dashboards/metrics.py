"""Evaluating a metric — a stored filter over a dataset, rolled up to one value.

This is the **one** evaluation seam. A metric card in a template, a dashboard
cell, a report column, the REST value route and the MCP ``metric_value`` /
``metric_preview`` tools all call :func:`evaluate`, so a number means the same
thing everywhere it appears. An unsaved metric (the builder's live preview, an
agent's dry run) is just a ``Metric`` instance that hasn't been saved — same
path, no second implementation to drift.

The pieces:

- **value** — ``Dataset.scalar()`` over the metric's ``filter_tree`` (AND-ed
  with a period leaf when a dashboard/report period applies);
- **state** — the first matching ``thresholds`` rule → a stat-card state
  (``success`` / ``warning`` / ``danger`` / ``muted``);
- **display** — ``format_value`` (number / compact / decimal / percent /
  currency / duration);
- **drill-down** — :func:`drill_rows`, the rows behind the number, through the
  same filter, so the count you click equals the rows you see.

Failure is explicit: an unknown dataset, a filter that no longer compiles, or a
dataset the viewer may not read yields a result with ``error`` /
``restricted`` set and **no number** — never a silently wider one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest, QueryDict

from apps.datasets.dateranges import is_period, period_label
from apps.datasets.filter_tree import FilterTreeError, and_trees, describe_filter_tree

if TYPE_CHECKING:
    from apps.datasets.core import Dataset

    from .models import Metric

logger = logging.getLogger(__name__)

#: What a rate says where a metric would show its rows.
RATE_NO_ROWS = "A rate has no rows of its own. Open either of its two metrics to see theirs."

#: Aggregations a metric may use (``count`` and ``distinct`` need no numeric measure).
AGGS: list[tuple[str, str]] = [
    ("count", "Count rows"),
    ("distinct", "Count distinct values"),
    ("sum", "Sum"),
    ("avg", "Average"),
    ("median", "Median"),
    ("min", "Minimum"),
    ("max", "Maximum"),
]
AGGS_NEEDING_MEASURE = frozenset({"sum", "avg", "median", "min", "max", "distinct"})
#: Aggregations that need a numeric column: words can be counted, not averaged.
NUMERIC_AGGS = frozenset({"sum", "avg", "median"})
#: How a hand-entered metric rolls up the entries in a period. "Latest" suits a
#: reading (CSAT, headcount), "Sum" an amount (spend).
MANUAL_AGGS: list[tuple[str, str]] = [
    ("latest", "Latest value"),
    ("sum", "Sum"),
    ("avg", "Average"),
    ("min", "Minimum"),
    ("max", "Maximum"),
]
ALL_AGGS: list[tuple[str, str]] = [*AGGS, ("latest", "Latest value")]


def aggs_available() -> list[tuple[str, str]]:
    """``AGGS`` as this database can compute them: no median where it has none
    (MySQL, MariaDB), so no picker, form or tool offers a number it can't give."""
    from apps.datasets.core import median_supported

    return [a for a in AGGS if a[0] != "median" or median_supported()]


def all_aggs_available() -> list[tuple[str, str]]:
    """:func:`aggs_available` plus the hand-entered roll-up ``latest``."""
    return [*aggs_available(), ("latest", "Latest value")]

#: How the number reads.
FORMATS: list[tuple[str, str]] = [
    ("number", "Number — 9,481"),
    ("compact", "Compact — 9.5K"),
    ("decimal", "Decimal — 9,481.24"),
    ("percent", "Percent — 94.2%"),
    ("currency", "Currency — $9,481.00"),
    ("duration", "Duration (seconds) — 2m 19s"),
]

#: The stat-card states a threshold rule may produce (see stat_card.html).
STATES = ("success", "warning", "danger", "muted")
THRESHOLD_OPS = (">", ">=", "<", "<=", "=", "!=", "between")
MAX_THRESHOLDS = 10


# -- thresholds ---------------------------------------------------------------


def validate_thresholds(raw: Any) -> list[str]:
    """Problems with a ``thresholds`` list (empty = valid). Shape:
    ``[{"op": ">=", "value": 10, "state": "danger"}, …]`` — ordered, first
    match wins; ``between`` takes ``[lo, hi]`` (inclusive)."""
    if raw in (None, [], ""):
        return []
    if not isinstance(raw, list):
        return ["thresholds must be a list of {op, value, state} rules"]
    if len(raw) > MAX_THRESHOLDS:
        return [f"at most {MAX_THRESHOLDS} threshold rules"]
    problems: list[str] = []
    for i, rule in enumerate(raw):
        where = f"thresholds[{i}]"
        if not isinstance(rule, dict):
            problems.append(f"{where}: expected an object")
            continue
        if rule.get("op") not in THRESHOLD_OPS:
            problems.append(f"{where}.op: use one of {list(THRESHOLD_OPS)}")
        if rule.get("state") not in STATES:
            problems.append(f"{where}.state: use one of {list(STATES)}")
        value = rule.get("value")
        if rule.get("op") == "between":
            if not (isinstance(value, list) and len(value) == 2 and all(_is_number(v) for v in value)):
                problems.append(f"{where}.value: 'between' takes [low, high]")
        elif not _is_number(value):
            problems.append(f"{where}.value: a number is required")
    return problems


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def state_for(value: Any, thresholds: Any) -> Optional[str]:
    """The state of the first rule *value* matches, or None."""
    if not _is_number(value) or not isinstance(thresholds, list):
        return None
    num = float(value)
    for rule in thresholds:
        if not isinstance(rule, dict):
            continue
        op, target = rule.get("op"), rule.get("value")
        try:
            if op == "between" and isinstance(target, list) and len(target) == 2:
                hit = float(target[0]) <= num <= float(target[1])
            elif target is not None and _is_number(target):
                t = float(target)
                hit = {
                    ">": num > t,
                    ">=": num >= t,
                    "<": num < t,
                    "<=": num <= t,
                    "=": num == t,
                    "!=": num != t,
                }.get(str(op), False)
            else:
                hit = False
        except (TypeError, ValueError):
            hit = False
        if hit and rule.get("state") in STATES:
            return str(rule["state"])
    return None


# -- formatting ---------------------------------------------------------------


def format_value(value: Any, fmt: str = "number", unit: str = "") -> str:
    """Render *value* for a card. ``None`` → "—". Non-numeric values (a date
    from ``max`` over a date column) render as text."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()
    if not _is_number(value):
        return str(value)
    num = float(value)
    if fmt == "compact":
        for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(num) >= size:
                return f"{num / size:.1f}".rstrip("0").rstrip(".") + suffix
        return _plain(num)
    if fmt == "decimal":
        return f"{num:,.2f}"
    if fmt == "percent":
        return f"{num:,.1f}%"
    if fmt == "currency":
        sign = "-" if num < 0 else ""
        return f"{sign}{unit or '$'}{abs(num):,.2f}"
    if fmt == "duration":
        return _duration(num)
    return _plain(num)


def _plain(num: float) -> str:
    return f"{int(num):,}" if num == int(num) else f"{num:,.2f}"


def _duration(seconds: float) -> str:
    total = int(round(seconds))
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{sign}{days}d {hours}h"
    if hours:
        return f"{sign}{hours}h {minutes:02d}m"
    if minutes:
        return f"{sign}{minutes}m {secs:02d}s"
    return f"{sign}{secs}s"


def display_unit(fmt: str, unit: str) -> str:
    """The trailing unit a card shows (currency puts its symbol up front)."""
    return "" if fmt in ("currency", "percent", "duration") else unit


# -- evaluation -----------------------------------------------------------------


@dataclass
class MetricResult:
    """What one evaluation produced. Exactly one of ``display``-with-a-value,
    ``error`` or ``restricted`` describes the outcome."""

    value: Any = None
    display: str = "—"
    unit: str = ""
    state: Optional[str] = None
    error: Optional[str] = None
    restricted: bool = False
    summary: str = ""
    period: Optional[str] = None
    period_label: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.restricted

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe form for REST/MCP."""
        value = self.value
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        return {
            "value": value,
            "display": self.display,
            "unit": self.unit,
            "state": self.state,
            "error": self.error,
            "restricted": self.restricted,
            "summary": self.summary,
            "period": self.period,
            "period_label": self.period_label,
            "problems": self.problems,
        }


def request_for(user: Any) -> HttpRequest:
    """A minimal request carrying *user* — for evaluating outside a view (MCP,
    the shell, a scheduled report). The dataset fn reads ``request.user`` for
    per-user scoping, so the user is the part that matters."""
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict("", mutable=False)
    req.META = {}
    return req


def resolve_dataset(metric: "Metric") -> Optional["Dataset"]:
    from apps.datasets.core import get_dataset

    return get_dataset(metric.dataset)


def rate_parts(metric: "Metric") -> tuple[Optional["Metric"], Optional["Metric"]]:
    """A rate's ``(numerator, denominator)``; None for one that no longer exists."""
    from .models import Metric

    found = {m.key: m for m in Metric.objects.filter(key__in=[metric.numerator, metric.denominator])}
    return found.get(metric.numerator), found.get(metric.denominator)


def rate_value(numerator: Any, denominator: Any, fmt: str) -> Any:
    """``numerator ÷ denominator``, ×100 for the percent format. None when either
    has no value or the denominator is 0: nothing happened, so there's no rate."""
    from apps.datasets.core import round_value

    if not _is_number(numerator) or not _is_number(denominator) or not float(denominator):
        return None
    ratio = float(numerator) / float(denominator)
    return round_value(ratio * 100 if fmt == "percent" else ratio)


def may_read(metric: "Metric", user: Any) -> bool:
    """Whether *user* may see *metric*'s number: its dataset's ``access`` tier.
    A rate reveals both its parts, so it takes both to read one."""
    from apps.datasets.registry import get_def, user_may_read

    if metric.is_rate:
        parts = rate_parts(metric)
        return all(p is not None and p.can_view(user) and may_read(p, user) for p in parts)
    if metric.is_manual and metric.pk is not None and not metric.can_view(user):
        # Its entries are scoped to the metrics a person can see, so another
        # user's hand-entered metric read "—", as if nothing were entered.
        return False
    dfn = get_def(metric.dataset)
    return dfn is not None and user_may_read(dfn, user)


def effective_tree(metric: "Metric", period: Optional[str] = None, extra: Any = None) -> Any:
    """The metric's filter AND-ed with a period leaf (when the metric is
    period-aware and a period is given) and any *extra* narrowing (a grouped
    card's group, a drill-down)."""
    period_leaf = None
    if period and metric.period_field and is_period(period):
        period_leaf = {"field": metric.period_field, "op": "period", "value": period}
    return and_trees(metric.filter_tree, period_leaf, extra)


def evaluate(
    metric: "Metric",
    request: HttpRequest,
    *,
    period: Optional[str] = None,
    extra_tree: Any = None,
) -> MetricResult:
    """Evaluate *metric* for the user on *request* (see module docstring)."""
    applied = period if (period and metric.period_field and is_period(period)) else None
    result = MetricResult(
        unit=display_unit(metric.format, metric.unit),
        period=applied,
        period_label=period_label(applied) if applied else "",
    )
    if metric.is_rate:
        return _evaluate_rate(metric, request, applied, extra_tree, result)
    ds = resolve_dataset(metric)
    if ds is None:
        result.error = f"Dataset “{metric.dataset}” is not available."
        return result
    result.summary = (
        metric.filter_summary
        if metric.is_manual
        else describe_filter_tree(effective_tree(metric, applied, extra_tree), ds.column_labels())
    )
    if not may_read(metric, getattr(request, "user", None)):
        result.restricted = True
        result.error = None
        return result
    try:
        tree = effective_tree(metric, applied, extra_tree)
        if metric.is_manual:
            value = _manual_value(metric, ds, request, tree)
        else:
            value = ds.scalar(
                measure=metric.measure or None,
                agg=metric.agg or "count",
                filter_tree=tree,
                request=request,
            )
    except FilterTreeError as exc:
        result.error = "This metric's filter no longer applies to its dataset."
        result.problems = exc.problems
        return result
    except ValueError as exc:
        result.error = str(exc)
        return result
    except Exception:  # noqa: BLE001 — one broken card must not take the page down
        logger.exception("metric %s: evaluation failed", getattr(metric, "key", "?"))
        result.error = "This metric could not be evaluated."
        return result
    result.value = value
    result.display = format_value(value, metric.format, metric.unit)
    result.state = state_for(value, metric.thresholds)
    return result


def _evaluate_rate(
    metric: "Metric", request: HttpRequest, period: Optional[str], extra_tree: Any, result: MetricResult
) -> MetricResult:
    """A rate over the same period on both sides. Anything that would divide two
    unlike numbers (a part gone, one part ignoring the period) is an error, never
    a figure: 5xx this week over all-time requests would look fine and be wrong."""
    numerator, denominator = rate_parts(metric)
    if numerator is None or denominator is None:
        missing = metric.numerator if numerator is None else metric.denominator
        result.error = f"This rate needs the metric “{missing}”, which no longer exists."
        return result
    result.summary = f"{numerator.name} ÷ {denominator.name}"
    if extra_tree:
        result.error = RATE_NO_ROWS
        return result
    if not may_read(metric, getattr(request, "user", None)):
        result.restricted = True
        return result
    if bool(numerator.period_field) != bool(denominator.period_field):
        result.error = "One side of this rate depends on time and the other doesn't, so they can't be compared."
        return result
    top, bottom = evaluate(numerator, request, period=period), evaluate(denominator, request, period=period)
    if top.restricted or bottom.restricted:
        result.restricted = True
        return result
    for part, outcome in ((numerator, top), (denominator, bottom)):
        if outcome.error:
            result.error = f"{part.name}: {outcome.error}"
            result.problems = outcome.problems
            return result
    result.value = rate_value(top.value, bottom.value, metric.format)
    result.display = format_value(result.value, metric.format, metric.unit)
    result.state = state_for(result.value, metric.thresholds)
    return result


def _manual_value(metric: "Metric", ds: "Dataset", request: HttpRequest, tree: Any) -> Any:
    """A hand-entered metric's value over *tree*. None when nothing was entered,
    even for a sum: a week nobody filled in is unknown, not zero."""
    from django.db.models import Avg, Max, Min, Sum

    from apps.datasets.core import round_value

    qs = ds.queryset(request, filter_tree=tree).order_by()
    if metric.agg == "latest":
        return round_value(qs.order_by("-date").values_list("value", flat=True).first())
    expr = {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[metric.agg]("value")
    return round_value(qs.aggregate(v=expr)["v"])


def manual_buckets(metric: "Metric", request: HttpRequest, tree: Any, start_of: Any) -> dict[date, Any]:
    """A hand-entered metric's entries under *tree*, rolled up per bucket:
    ``{start_of(day): value}``. Done here rather than by ``Dataset.series`` because
    "latest" isn't a database aggregate, and a metric's entries are few."""
    from apps.datasets.core import round_value

    ds = resolve_dataset(metric)
    if ds is None:
        raise ValueError(f"dataset {metric.dataset!r} is not available")
    buckets: dict[date, list[Decimal]] = {}
    for day, value in ds.queryset(request, filter_tree=tree).order_by("date").values_list("date", "value"):
        buckets.setdefault(start_of(day), []).append(value)
    roll_up: Any = {
        "latest": lambda v: v[-1],
        "sum": sum,
        "avg": lambda v: sum(v) / len(v),
        "min": min,
        "max": max,
    }[metric.agg]
    return {start: round_value(roll_up(values)) for start, values in buckets.items()}


# -- grouped values (the metric_group card) ---------------------------------------

#: Ceiling on the groups one card shows.
MAX_GROUPS = 12


def group_values(
    metric: "Metric",
    request: HttpRequest,
    dimension: str,
    *,
    limit: int = 5,
    other: bool = True,
    period: Optional[str] = None,
) -> list[dict[str, Any]]:
    """The metric split by *dimension*: the top ``limit`` groups by value,
    biggest first, each ``{label, raw, value, display, state}`` — plus an
    ``Other`` row folding the tail when ``other`` is set and the aggregation
    is additive (count/sum; an average of the tail isn't the tail's average,
    so non-additive aggregations show no Other rather than a wrong one).

    Raises ``ValueError`` / ``FilterTreeError`` on a bad dimension or filter;
    the caller renders the error. Values come from the dataset's public
    ``queryset()`` seam with the same aggregate ``scalar()`` uses, so the
    groups and the card's total reconcile.
    """
    from apps.datasets.core import round_value

    ds = resolve_dataset(metric)
    if ds is None:
        raise ValueError(RATE_NO_ROWS if metric.is_rate else f"dataset {metric.dataset!r} is not available")
    if dimension not in set(ds.column_names()):
        raise ValueError(f"unknown dimension {dimension!r}")
    limit = max(1, min(int(limit or 5), MAX_GROUPS))
    tree = effective_tree(metric, period)
    qs = ds.queryset(request, filter_tree=tree)
    declared = ds.declared_measures()
    is_ratio = bool(metric.measure) and metric.measure in declared
    expr = ds.aggregate_expression(metric.agg, metric.measure or None)
    rows = list(qs.order_by().values(dimension).annotate(_value=expr))
    rows.sort(key=lambda r: (r["_value"] is not None, r["_value"] or 0), reverse=True)
    kept = rows[:limit]
    labels = ds.value_labels(dimension, kept)
    out: list[dict[str, Any]] = []
    for row in kept:
        raw = row[dimension]
        value = round_value(row["_value"])
        label = labels.get(raw) if labels else None
        if label is None:
            label = "—" if raw is None else ("Yes" if raw is True else "No" if raw is False else str(raw))
        out.append(
            {
                "label": label,
                "raw": raw,
                "value": value,
                "display": format_value(value, metric.format, metric.unit),
                "state": state_for(value, metric.thresholds),
            }
        )
    if other and len(rows) > limit and not is_ratio and (metric.agg or "count") in ("count", "sum"):
        tail = sum((r["_value"] or 0) for r in rows[limit:])
        out.append(
            {
                "label": "Other",
                "raw": None,
                "value": tail,
                "display": format_value(tail, metric.format, metric.unit),
                "state": None,
                "other": True,
                "exclude": [r[dimension] for r in kept],
            }
        )
    return out


def group_value_map(metric: "Metric", request: HttpRequest, dimension: str, period: Optional[str]) -> dict[Any, Any]:
    """``{raw group value: aggregate}`` for every group (no top-N cut) — what a
    grouped card compares its current groups against for the previous period.
    Same queryset seam and aggregate as :func:`group_values`."""
    from apps.datasets.core import round_value

    ds = resolve_dataset(metric)
    if ds is None or dimension not in set(ds.column_names()):
        return {}
    expr = ds.aggregate_expression(metric.agg, metric.measure or None)
    qs = ds.queryset(request, filter_tree=effective_tree(metric, period))
    return {r[dimension]: round_value(r["_value"]) for r in qs.order_by().values(dimension).annotate(_value=expr)}


def group_leaf(dimension: str, raw: Any) -> dict[str, Any]:
    """The filter-tree leaf selecting one group (``None`` → isnull)."""
    if raw is None:
        return {"field": dimension, "op": "isnull", "value": True}
    return {"field": dimension, "op": "=", "value": raw}


# -- drill-down -------------------------------------------------------------------

DRILL_LIMIT = 50
DRILL_COLUMNS = 6
#: A card's drill-down (``options.drilldown``): which columns the rows modal
#: shows, how each is formatted, the sort and how many rows. Its export (CSV)
#: uses the same columns, up to EXPORT_LIMIT rows.
DRILL_FORMATS: list[list[str]] = [
    ["", "As stored"],
    ["number", "Number — 9,481"],
    ["compact", "Compact — 9.5K"],
    ["decimal", "Decimal — 9,481.24"],
    ["percent", "Percent — 94.2%"],
    ["currency", "Currency — $9,481.00"],
    ["duration", "Duration — 2m 19s"],
    ["date", "Date — 2026-11-02"],
    ["datetime", "Date and time — 2026-11-02 14:05"],
    ["yesno", "Yes / no"],
]
MAX_DRILL_COLUMNS = 12
MAX_DRILL_ROWS = 500
EXPORT_LIMIT = 10_000
_DRILL_KEYS = {"columns", "sort", "limit"}


def validate_drilldown(spec: Any, column_names: Optional[list[str]]) -> list[str]:
    """Problems with a drill-down design (empty = valid). *column_names* are
    the dataset's columns (``None`` = unknown yet: shape checks only).

    ``{"columns": [{"field": "path", "label"?: "Path", "format"?: "date"}],
    "sort"?: "-timestamp", "limit"?: 1–500}``; a bare field name is shorthand
    for ``{"field": name}``."""
    if not isinstance(spec, dict):
        return ["drilldown must be an object"]
    problems: list[str] = []
    unknown = sorted(set(spec) - _DRILL_KEYS)
    if unknown:
        problems.append(f"drilldown: unknown key(s) {unknown}")
    columns = spec.get("columns", [])
    if not isinstance(columns, list) or len(columns) > MAX_DRILL_COLUMNS:
        problems.append(f"drilldown.columns: a list of at most {MAX_DRILL_COLUMNS} columns")
        columns = []
    formats = {f for f, _ in DRILL_FORMATS}
    for n, col in enumerate(columns):
        col = {"field": col} if isinstance(col, str) else col
        where = f"drilldown.columns[{n}]"
        if not isinstance(col, dict) or not isinstance(col.get("field"), str):
            problems.append(f"{where}: needs a field")
            continue
        if column_names is not None and col["field"] not in column_names:
            problems.append(f"{where}: the dataset has no column {col['field']!r}")
        if col.get("format", "") not in formats:
            problems.append(f"{where}.format: one of {sorted(f for f in formats if f)}")
        if "label" in col and (not isinstance(col["label"], str) or len(col["label"]) > 60):
            problems.append(f"{where}.label: text, at most 60 characters")
    sort = spec.get("sort", "")
    if sort:
        if not isinstance(sort, str):
            problems.append("drilldown.sort: a column name, - for descending")
        elif column_names is not None and sort.lstrip("-") not in column_names:
            problems.append(f"drilldown.sort: the dataset has no column {sort.lstrip('-')!r}")
    limit = spec.get("limit", DRILL_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_DRILL_ROWS:
        problems.append(f"drilldown.limit: 1–{MAX_DRILL_ROWS} rows")
    return problems


def requested_drilldown(raw: Any, metric: "Metric") -> tuple[Optional[dict[str, Any]], str]:
    """A card's drill-down design as a rows URL carries it (``?drill=<json>``,
    what ``components.drill_params`` adds), validated against the metric's
    dataset — ``(spec or None, problem)``. It can only pick, label, format and
    sort columns of rows the viewer may already read."""
    if not raw:
        return None, ""
    try:
        spec = json.loads(raw)
    except ValueError:
        return None, "Bad drill-down design."
    ds = resolve_dataset(metric)
    problems = validate_drilldown(spec, ds.column_names() if ds is not None else None)
    return (None, "; ".join(problems)) if problems else (spec, "")


def format_cell(value: Any, fmt: str, column_type: str = "") -> Any:
    """A drill-down cell under a column's format ("" = as stored, with
    datetimes shortened to local ``YYYY-MM-DD HH:MM``)."""
    if value is None:
        return ""
    if isinstance(value, dict):  # an expanded foreign key
        value = value.get("name") or value.get("id")
    if fmt in ("date", "datetime") and isinstance(value, str):
        short = _short_datetime(value)
        return short[:10] if fmt == "date" else short
    if fmt == "yesno":
        return "Yes" if value in (True, "true", "True", 1) else "No" if value in (False, "false", "False", 0) else value
    if fmt and fmt not in ("date", "datetime"):
        return format_value(value, fmt)
    if column_type == "datetime" and isinstance(value, str):
        return _short_datetime(value)
    return value


def _drill_columns(ds: Any, spec: Optional[dict[str, Any]]) -> list[dict[str, str]]:
    labels = ds.column_labels()
    if spec and spec.get("columns"):
        out = []
        for col in spec["columns"]:
            col = {"field": col} if isinstance(col, str) else col
            out.append({"name": col["field"], "label": col.get("label") or labels.get(col["field"], col["field"]),
                        "format": col.get("format", "")})
        return out
    return [{"name": n, "label": labels.get(n, n), "format": ""} for n in ds.column_names()[:DRILL_COLUMNS]]


def drill_rows(
    metric: "Metric",
    request: HttpRequest,
    *,
    period: Optional[str] = None,
    extra_tree: Any = None,
    limit: int = DRILL_LIMIT,
    spec: Optional[dict[str, Any]] = None,
    order: str = "",
    offset: int = 0,
) -> dict[str, Any]:
    """The rows behind a metric's number: ``{columns, rows, total}``. Same
    effective filter as :func:`evaluate`, so ``total`` equals a count metric's
    value. *spec* is a card's drill-down design (:func:`validate_drilldown`):
    its columns, formats, sort and row limit; without one, the dataset's first
    columns as stored. *order* (a column, ``-`` for descending — a clicked
    header) overrides the design's sort; *offset* skips rows after ordering (a
    card that pages). Raises like ``Dataset.rows`` does."""
    from apps.datasets.core import LINK_KEY

    ds = resolve_dataset(metric)
    if ds is None:
        raise ValueError(RATE_NO_ROWS if metric.is_rate else f"dataset {metric.dataset!r} is not available")
    tree = effective_tree(metric, period, extra_tree)
    columns = _drill_columns(ds, spec)
    if spec:
        limit = int(spec.get("limit") or limit)
    sort = order or (spec or {}).get("sort") or ("-date" if metric.is_manual else "")
    rows = ds.rows(
        filter_tree=tree,
        limit=limit,
        offset=offset,
        request=request,
        ordering=sort,
        expand=sorted(ds.fk_column_names()),
    )
    total = ds.count(request, filter_tree=tree)
    types = dict(ds.columns())
    shaped = [
        {
            "cells": [format_cell(row.get(c["name"]), c["format"], types.get(c["name"], "")) for c in columns],
            "url": row.get(LINK_KEY),
        }
        for row in rows
    ]
    for c in columns:
        c["type"] = types.get(c["name"], "")
    return {"columns": columns, "rows": shaped, "total": total, "sort": sort}


def drill_csv(
    metric: "Metric",
    request: HttpRequest,
    *,
    period: Optional[str] = None,
    extra_tree: Any = None,
    spec: Optional[dict[str, Any]] = None,
    order: str = "",
) -> tuple[list[str], list[list[Any]]]:
    """The drill-down's export: ``(headers, rows)`` with the same columns,
    formats and order as the modal (*order* = a clicked header), up to
    :data:`EXPORT_LIMIT` rows."""
    ds = resolve_dataset(metric)
    if ds is None:
        raise ValueError(RATE_NO_ROWS if metric.is_rate else f"dataset {metric.dataset!r} is not available")
    tree = effective_tree(metric, period, extra_tree)
    columns = _drill_columns(ds, spec)
    rows = ds.rows(
        filter_tree=tree,
        limit=EXPORT_LIMIT,
        request=request,
        ordering=order or (spec or {}).get("sort") or ("-date" if metric.is_manual else ""),
        expand=sorted(ds.fk_column_names()),
    )
    types = dict(ds.columns())
    body = [[format_cell(row.get(c["name"]), c["format"], types.get(c["name"], "")) for c in columns] for row in rows]
    return [c["label"] for c in columns], body


def _short_datetime(text: str) -> str:
    """ISO datetime → local ``YYYY-MM-DD HH:MM`` for a drill-down cell."""
    from django.utils import timezone

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if timezone.is_aware(parsed):
        parsed = timezone.localtime(parsed)
    return parsed.strftime("%Y-%m-%d %H:%M")


# -- a metric in words --------------------------------------------------------------

_AGG_PHRASES = {
    "count": "Count of rows in",
    "distinct": "Distinct {measure} in",
    "sum": "Total {measure} across",
    "avg": "Average {measure} across",
    "min": "Lowest {measure} in",
    "max": "Highest {measure} in",
}

_MANUAL_PHRASES = {
    "latest": "Latest value",
    "sum": "Total of the values",
    "avg": "Average of the values",
    "min": "Lowest of the values",
    "max": "Highest of the values",
}


def metric_sentence(metric: "Metric", result: MetricResult) -> dict[str, str]:
    """The metric read as a sentence, in parts a template can weight:
    ``{lead, dataset, where, when}`` — "Average response time across |
    Requests | where Status code < 400 | in the last 30 days". *result* is
    the metric evaluated for the period being shown."""
    from .periods import period_phrase, plain_reading

    if metric.is_rate or metric.is_manual:
        when = period_phrase(result.period) if result.period else ("over all time" if metric.period_field else "")
        if metric.is_rate:
            top, bottom = rate_parts(metric)
            return {
                "lead": f"{top.name if top else metric.numerator} divided by",
                "dataset": bottom.name if bottom else metric.denominator,
                "where": "",
                "every": "",
                "when": when,
                "full": result.summary,
            }
        return {
            "lead": _MANUAL_PHRASES.get(metric.agg, "Value"),
            "dataset": "entered by hand",
            "where": "",
            "every": "",
            "when": when,
            "full": result.summary,
        }
    ds = resolve_dataset(metric)
    lead = _AGG_PHRASES.get(metric.agg, "{measure} of").format(measure=metric.measure_label or "values")
    base = plain_reading(metric.filter_summary)
    when = ""
    if result.period:
        when = period_phrase(result.period)
    elif metric.period_field:
        when = "over all time"
    return {
        "lead": lead,
        "dataset": ds.dfn.label if ds is not None else metric.dataset,
        "where": "" if base == "All rows" else f"where {base}",
        "every": "every row" if base == "All rows" else "",
        "when": when,
        "full": result.summary,
    }


def threshold_legend(metric: "Metric") -> list[dict[str, str]]:
    """The colour rules as ``{state, text}`` ("≥ 5" is danger), first match first."""
    out = []
    for rule in metric.thresholds if isinstance(metric.thresholds, list) else []:
        if not isinstance(rule, dict):
            continue
        op, value = rule.get("op"), rule.get("value")
        if op == "between" and isinstance(value, list) and len(value) == 2:
            text = f"{value[0]}–{value[1]}"
        else:
            text = f"{ {'>=': '≥', '<=': '≤', '!=': '≠'}.get(str(op), op) } {value}"
        out.append({"state": str(rule.get("state", "")), "text": text})
    return out
