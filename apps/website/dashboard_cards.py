"""A chart card for dashboards — the reference for adding your own card type.

SmallStack's own dashboard cards are stat and roll-up cards. A chart is a
project's choice, so it lives here, in the app your project owns, and plugs in
through the one public seam a downstream app uses::

    register_component_type(ComponentType(...))   # from AppConfig.ready()

Everything else comes with the seam: the card is stored in ``Dashboard.layout``
like any other, validated on save from every surface, offered in the "Add card"
dialog (from ``options_schema``), placeable by an agent over MCP / REST, lazily
loaded, refreshed, and access-checked. The numbers come from
``apps.dashboards.trends.metric_trend`` — the same series
``GET dashboards/api/metrics/<key>/trend/`` and the ``metric_trend`` MCP tool
return — so swapping this inline drawing for ECharts or any other library
changes the template, not the data.

It is also the reference for a ``stylable`` type: the shared card styling and
the card's own colour rules (``options.style`` / ``options.thresholds``) come
through ``card_style(cell)`` and ``styled_value(...)``, and the template puts
``style.classes`` on its root for ``dashboard-cards.css`` to style.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from django.urls import reverse

from apps.dashboards.components import (
    CellContext,
    ComponentType,
    _validate_group,
    build_metric_group,
    card_style,
    cell_title,
    drill_params,
    register_component_type,
    styled_value,
)
from apps.dashboards.trends import metric_trend
from apps.datasets.core import get_dataset

KINDS = (("bars", "Bars"), ("line", "Line"))
GRAIN_CHOICES = (
    ("", "Fit the period"),
    ("day", "Days"),
    ("week", "Weeks"),
    ("month", "Months"),
    ("quarter", "Quarters"),
)


def validate_trend(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    problems = []
    if opts.get("kind", "bars") not in dict(KINDS):
        problems.append(f"'kind' must be one of {[k for k, _ in KINDS]}")
    if opts.get("grain", "") not in dict(GRAIN_CHOICES):
        problems.append(f"'grain' must be one of {[g for g, _ in GRAIN_CHOICES if g]} (or omitted)")
    return problems


def build_trend(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The template context: the series from ``metric_trend`` plus what the
    drawing needs — each bucket's height as a fraction of the tallest, its
    rows URL (the bucket's ``[lo, hi)`` narrowing), and the SVG line."""
    metric = ctx.metric
    assert metric is not None
    opts = cell.get("options") or {}
    trend = metric_trend(metric, ctx.request, ctx.period, opts.get("grain") or None)
    label = cell_title(cell) or metric.name
    style = card_style(cell)
    context: dict[str, Any] = {
        "label": label,
        "trend": trend,
        "kind": opts.get("kind", "bars"),
        "points": [],
        "style": style,
        "unit": styled_value(None, metric, style, None)["unit"],
    }
    if not trend["ok"]:
        return context
    values = [p["value"] for p in trend["points"] if isinstance(p["value"], (int, float))]
    top = max(values, default=0) or 1
    rows_url = reverse("dashboards_metric_rows", kwargs={"key": metric.key})
    n = len(trend["points"])
    drill = drill_params(cell)
    line = []
    for i, p in enumerate(trend["points"]):
        value = p["value"]
        share = (value / top) if isinstance(value, (int, float)) else None
        # The card's format, unit and colour rules (else the metric's) per bucket.
        shown = styled_value(value, metric, style, p.get("state")) if value is not None else {}
        context["points"].append(
            {
                **p,
                "display": shown.get("display", p["display"]),
                "state": shown.get("state", p.get("state")),
                "share": f"{share:.4f}" if share is not None else None,
                # The bucket's rows, shown with the card's drill-down design (if it has one).
                "rows_url": f"{rows_url}?{urlencode({'narrow': json.dumps(p['narrow'], default=str), **drill})}",
                "title": f"{label}, {p['label']}",
            }
        )
        if share is not None:
            # SVG user units: 100 wide, 40 tall; each bucket's centre on x.
            line.append(f"{(i + 0.5) * 100 / n:.2f},{40 - share * 36:.2f}")
    context["line"] = " ".join(line)
    context["latest"] = context["points"][-1] if context["points"] else None  # styled, like the bars
    context["first_label"] = trend["points"][0]["label"] if trend["points"] else ""
    context["last_label"] = trend["points"][-1]["label"] if trend["points"] else ""
    return context


def _group_options(default_limit: int) -> list[dict[str, Any]]:
    return [
        {"name": "dimension", "label": "Group by", "type": "column", "required": True},
        {"name": "limit", "label": "Groups shown", "type": "integer", "default": default_limit, "min": 1, "max": 12},
        {"name": "other", "label": "Fold the rest into “Other”", "type": "boolean", "default": True},
    ]


def _validated_groups(cell: dict[str, Any]) -> list[str]:
    return _validate_group({**cell, "options": {"limit": 6, **(cell.get("options") or {})}})


def build_pie(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """Each group's share of the whole, as SVG. A circle of circumference 100 makes a
    share its own dash length, so a slice is one stroked circle. Shares only mean
    something for a count or a sum: averages don't add up to a whole, so those say
    so rather than drawing a pie that looks right and isn't."""
    context = build_metric_group({**cell, "options": {"limit": 6, **(cell.get("options") or {})}}, ctx)
    if context.get("restricted") or context.get("error"):
        return context
    metric = ctx.metric
    assert metric is not None
    ds = get_dataset(metric.dataset)
    declared = ds.declared_measures() if ds is not None else {}
    if metric.agg not in ("count", "sum") or metric.measure in declared:
        message = "A pie shows shares of a whole, so it needs a count or a sum. Ranked bars suit this metric."
        return {**context, "groups": [], "error": message}
    groups = [g for g in context["groups"] if isinstance(g["value"], (int, float, Decimal)) and g["value"] > 0]
    whole = sum(float(g["value"]) for g in groups)
    start = 0.0
    slices = []
    for i, g in enumerate(groups):
        share = float(g["value"]) / whole * 100
        # Stroke from 12 o'clock: an SVG circle's dash starts at 3 o'clock, 25 units on.
        slices.append(
            {
                **g,
                "share": f"{share:.2f}",
                "rest": f"{100 - share:.2f}",
                "offset": f"{25 - start:.2f}",
                "percent": f"{share:.0f}%" if share >= 1 else "<1%",
                "series": 0 if g.get("other") else i % 8 + 1,
            }
        )
        start += share
    return {**context, "groups": groups, "slices": slices}


def build_ranked(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The groups as bars, largest first, each as long as its share of the largest.
    Works for any aggregation, because it compares groups rather than adding them."""
    context = build_metric_group({**cell, "options": {"limit": 6, **(cell.get("options") or {})}}, ctx)
    if context.get("restricted") or context.get("error"):
        return context
    numbers = [abs(float(g["value"])) for g in context["groups"] if isinstance(g["value"], (int, float, Decimal))]
    top = max(numbers, default=0) or 1
    bars = [
        {**g, "share": f"{abs(float(g['value'])) / top:.4f}" if isinstance(g["value"], (int, float, Decimal)) else "0"}
        for g in context["groups"]
    ]
    return {**context, "bars": bars}


def register() -> None:
    register_component_type(
        ComponentType(
            key="pie",
            label="Pie chart",
            description="A count or total split by a column: each group's share of the whole. Each one opens its rows.",
            group="Charts",
            stylable=True,
            drillable=True,
            icon="M11 2v20a10 10 0 0 1 0-20zm2 0v9h9a10 10 0 0 0-9-9zm0 11v9a10 10 0 0 0 9-9h-9z",
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/pie.html",
            build=build_pie,
            needs_metric=True,
            default_size=(4, 3),
            requires=frozenset({"dimension"}),
            validate=_validated_groups,
            options_schema=_group_options(6),
        )
    )
    register_component_type(
        ComponentType(
            key="ranked",
            label="Ranked bars",
            description="A metric split by a column: its groups as bars, largest first. Each one opens its rows.",
            group="Charts",
            stylable=True,
            drillable=True,
            icon="M4 5h16v3H4V5zm0 5.5h11v3H4v-3zM4 16h7v3H4v-3z",
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/ranked.html",
            build=build_ranked,
            needs_metric=True,
            default_size=(4, 3),
            requires=frozenset({"dimension"}),
            validate=_validated_groups,
            options_schema=_group_options(6),
        )
    )
    register_component_type(
        ComponentType(
            key="trend",
            label="Trend chart",
            description="A metric over time — bars or a line per day, week or month. Each bucket opens its rows.",
            group="Charts",
            stylable=True,  # takes the shared card styling and its own colour rules
            drillable=True,  # its buckets open rows: it takes a drill-down design
            icon="M3.5 18.5l6-6 4 4L22 6.92 20.59 5.5l-7.09 8-4-4L2 17l1.5 1.5z",
            # A chart built on a library would list its files here, e.g.
            # media={"js": ["website/vendor/echarts.min.js", "website/js/charts.js"]}.
            # This one is plain server-rendered SVG, so it needs only its stylesheet.
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/trend.html",
            build=build_trend,
            needs_metric=True,
            default_size=(6, 3),
            requires=frozenset({"date"}),
            validate=validate_trend,
            options_schema=[
                {"name": "kind", "label": "Chart", "type": "choice", "choices": list(KINDS), "default": "bars"},
                {
                    "name": "grain",
                    "label": "Buckets",
                    "type": "choice",
                    "choices": list(GRAIN_CHOICES),
                    "default": "",
                    "help": "The metric needs a period field; the dashboard's period sets the span.",
                },
            ],
        )
    )
