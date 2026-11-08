"""A metric over time — the series any chart reads.

:func:`metric_trend` evaluates a metric's own filter and aggregation per
calendar bucket (day / week / month / quarter / year) across a period, through
``Dataset.series(grain=…)``. SmallStack ships no chart card — its dashboards
stay stat and roll-up cards — but a downstream chart (inline SVG, ECharts,
anything) and an agent read the same numbers from here, from
``GET dashboards/api/metrics/<key>/trend/`` or from the ``metric_trend`` MCP
tool, so a bar means what the stat card means.

The series is honest about time:

- **every bucket** of the period is present — an empty day reads 0 for an
  additive aggregation (count, distinct, sum) and as a gap (``None``) for one
  where nothing isn't zero (average, min, max, a ratio);
- the bucket still running (this week, today) carries ``partial: true``;
- each point carries ``narrow`` — the ``[lo, hi)`` filter that selects its rows,
  ready for the rows modal's ``?narrow=``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest
from django.utils import timezone

from apps.datasets.core import GRAINS, grain_label, grain_next
from apps.datasets.dateranges import period_label, relative_dates
from apps.datasets.filter_tree import FilterTreeError

from .metrics import (
    display_unit,
    effective_tree,
    format_value,
    manual_buckets,
    may_read,
    rate_parts,
    rate_value,
    resolve_dataset,
    state_for,
)
from .periods import period_heading

if TYPE_CHECKING:
    from .models import Metric

#: The most buckets one trend returns (a year of days fits).
MAX_BUCKETS = 400
_ADDITIVE = frozenset({"count", "distinct", "sum"})


def default_grain(since: Optional[date], until: Optional[date]) -> str:
    """The grain that gives a readable number of bars for a span: days up to a
    month, weeks up to four months, months up to two years, then quarters."""
    if since is None or until is None:
        return "month"
    days = (until - since).days
    if days <= 31:
        return "day"
    if days <= 120:
        return "week"
    if days <= 731:
        return "month"
    return "quarter"


def data_span(metric: "Metric", request: HttpRequest, tree: Any) -> tuple[Optional[date], Optional[date]]:
    """The first and last dates the metric's filtered rows carry, for "all
    time", which has no span of its own to fit buckets to: a week of data
    reads by day, three years by quarter. ``(None, None)`` when there are no
    rows or the question can't be asked (a rate, a hand-entered metric, a
    filter that no longer applies — the series call reports that)."""
    from django.db.models import Max, Min

    ds = resolve_dataset(metric)
    if ds is None or metric.is_rate or metric.is_manual or not metric.period_field:
        return None, None
    try:
        bounds = ds.queryset(request, filter_tree=tree).aggregate(
            lo=Min(metric.period_field), hi=Max(metric.period_field)
        )
    except Exception:  # noqa: BLE001 — a bad filter or column: the series says why
        return None, None

    def day(value: Any) -> Optional[date]:
        if isinstance(value, datetime):
            return (timezone.localtime(value) if timezone.is_aware(value) else value).date()
        return value if isinstance(value, date) else None

    return day(bounds.get("lo")), day(bounds.get("hi"))


def _bucket_start(d: date, grain: str) -> date:
    if grain == "week":
        return d - timedelta(days=d.weekday())
    if grain == "month":
        return d.replace(day=1)
    if grain == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    if grain == "year":
        return d.replace(month=1, day=1)
    return d


def _rate_rows(metric: "Metric", request: HttpRequest, period: Optional[str], grain: str) -> list[dict[str, Any]]:
    """A rate's series: its two parts' buckets, divided bucket by bucket."""
    numerator, denominator = rate_parts(metric)
    if numerator is None or denominator is None:
        raise ValueError("This rate's two metrics can't be compared.")
    top, bottom = metric_trend(numerator, request, period, grain), metric_trend(denominator, request, period, grain)
    for part in (top, bottom):
        if part["restricted"] or part["error"]:
            raise ValueError(part["error"] or "You don't have access to one of this rate's metrics.")
    below = {p["lo"]: p["value"] for p in bottom["points"]}
    return [
        {"lo": p["lo"], "hi": p["hi"], "value": rate_value(p["value"], below.get(p["lo"]), metric.format)}
        for p in top["points"]
    ]


def metric_trend(
    metric: "Metric", request: HttpRequest, period: Optional[str] = None, grain: Optional[str] = None
) -> dict[str, Any]:
    """*metric* per bucket across *period* (None = all time, up to the last
    :data:`MAX_BUCKETS` buckets with data). Returns ``{ok, error,
    restricted, period, heading, grain, unit, points: [{label, lo, hi, value,
    display, state, partial, narrow}]}``. *grain* defaults to
    :func:`default_grain` for the period's span — over all time, for the span
    of the data itself (:func:`data_span`). Never raises for a bad
    metric — ``error`` says why there's no series."""
    applied = period if (period and relative_dates(period)) else None
    out: dict[str, Any] = {
        "ok": False,
        "error": None,
        "restricted": False,
        "period": applied,
        "heading": period_heading(applied),
        "period_label": period_label(applied) if applied else "All time",
        "grain": None,
        "unit": display_unit(metric.format, metric.unit),
        "points": [],
    }
    if not metric.period_field:
        out["error"] = (
            "This metric has no period field, so it can't be read over time. "
            "Set one in the metric's settings: the date column it is read over."
        )
        return out
    ds = resolve_dataset(metric)
    if ds is None and not metric.is_rate:
        out["error"] = f"Dataset “{metric.dataset}” is not available."
        return out
    if not may_read(metric, getattr(request, "user", None)):
        out["restricted"] = True
        return out
    span = relative_dates(applied) if applied else None
    since, until = span if span else (None, None)
    if grain not in GRAINS:
        grain = (
            default_grain(since, until)
            if span
            else default_grain(*data_span(metric, request, effective_tree(metric, None)))
        )
    out["grain"] = grain
    try:
        if metric.is_rate:
            rows = _rate_rows(metric, request, applied, grain)
        elif metric.is_manual:
            tree = effective_tree(metric, applied)
            buckets = manual_buckets(metric, request, tree, lambda d: _bucket_start(d, grain))
            rows = [
                {"lo": s.isoformat(), "hi": grain_next(s, grain).isoformat(), "value": buckets[s]}
                for s in sorted(buckets)
            ]
        else:
            assert ds is not None  # only a rate gets past the check above without one
            rows = ds.series(
                metric.period_field,
                measure=metric.measure or None,
                agg=metric.agg or "count",
                grain=grain,
                # All time fits its grain to the data's span, so it gets the same cap:
                # a fixed 12 drew 12 of a fortnight's days, labelled all time.
                limit=MAX_BUCKETS,
                filter_tree=effective_tree(metric, applied),
                request=request,
            )
    except FilterTreeError:
        out["error"] = "This metric's filter no longer applies to its dataset."
        return out
    except ValueError as exc:
        out["error"] = str(exc)
        return out

    by_start = {str(r["lo"])[:10]: r for r in rows}
    if since is not None and until is not None:
        starts: list[date] = []
        cursor = _bucket_start(since, grain)
        while cursor < until and len(starts) < MAX_BUCKETS:
            starts.append(cursor)
            cursor = grain_next(cursor, grain)
    else:
        starts = [date.fromisoformat(str(r["lo"])[:10]) for r in rows]

    # A hand-entered week nobody filled in is unknown, and a rate over nothing isn't 0.
    empty_is_zero = (
        ds is not None
        and not metric.is_manual
        and (metric.agg or "count") in _ADDITIVE
        and metric.measure not in ds.declared_measures()
    )
    now = timezone.localtime() if timezone.is_aware(timezone.now()) else datetime.now()
    today = now.date()
    for start in starts:
        row = by_start.get(start.isoformat())
        end = grain_next(start, grain)
        value = row["value"] if row else (0 if empty_is_zero else None)
        # A number for a chart and for JSON: over MCP a Decimal arrives as a string.
        value = float(value) if isinstance(value, Decimal) else value
        lo = row["lo"] if row else start.isoformat()
        hi = row["hi"] if row else end.isoformat()
        out["points"].append(
            {
                "label": grain_label(start, grain),
                "lo": lo,
                "hi": hi,
                "value": value,
                "display": format_value(value, metric.format, metric.unit) if value is not None else "—",
                "state": state_for(value, metric.thresholds) if value is not None else None,
                "partial": start <= today < end,
                "narrow": {
                    "and": [
                        {"field": metric.period_field, "op": ">=", "value": lo},
                        {"field": metric.period_field, "op": "<", "value": hi},
                    ]
                },
            }
        )
    out["ok"] = True
    return out
