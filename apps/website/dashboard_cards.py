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
import math
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Sum
from django.http import HttpRequest

from apps.dashboards.components import (
    CellContext,
    ComponentType,
    _validate_group,
    build_metric_group,
    card_style,
    cell_title,
    drill_params,
    metric_card_context,
    register_component_type,
    rows_url,
    styled_value,
)
from apps.dashboards.metrics import (
    drill_rows,
    effective_tree,
    format_cell,
    may_read,
    resolve_dataset,
    validate_drilldown,
)
from apps.dashboards.trends import metric_trend
from apps.datasets.core import get_dataset
from apps.datasets.filter_tree import FilterTreeError

KINDS = (("bars", "Bars"), ("line", "Line"))
GRAIN_CHOICES = (
    ("", "Fit"),
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
    n = len(trend["points"])
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
                "rows_url": rows_url(ctx, narrow=json.dumps(p["narrow"], default=str), **drill_params(cell)),
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


# -- bar chart: the groups as columns or bars, by size or by name ---------------------

DIRECTIONS = (("vertical", "Columns"), ("horizontal", "Bars"))
ORDERS = (("value", "Largest first"), ("label", "By name"))


def validate_bars(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    problems = _validated_groups(cell)
    if opts.get("direction", "vertical") not in dict(DIRECTIONS):
        problems.append(f"'direction' must be one of {[d for d, _ in DIRECTIONS]}")
    if opts.get("order", "value") not in dict(ORDERS):
        problems.append(f"'order' must be one of {[o for o, _ in ORDERS]}")
    return problems


def build_bars(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The groups as a bar chart: columns (an axis of names under them) or
    bars (names beside them), largest first or in name order with "Other"
    last. Each bar is as long as its share of the largest, so any aggregation
    draws; the value sits at the bar's end."""
    context = build_metric_group({**cell, "options": {"limit": 8, **(cell.get("options") or {})}}, ctx)
    if context.get("restricted") or context.get("error"):
        return context
    opts = cell.get("options") or {}
    groups = list(context["groups"])
    if opts.get("order") == "label":
        groups.sort(key=lambda g: (bool(g.get("other")), str(g["label"]).lower()))
    numbers = [abs(float(g["value"])) for g in groups if isinstance(g["value"], (int, float, Decimal))]
    top = max(numbers, default=0) or 1
    bars = [
        {**g, "share": f"{abs(float(g['value'])) / top:.4f}" if isinstance(g["value"], (int, float, Decimal)) else "0"}
        for g in groups
    ]
    return {**context, "bars": bars, "direction": opts.get("direction", "vertical")}


# -- gauge: one number on a dial between a floor and a ceiling ------------------------


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_gauge(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    lo, hi = _number(opts.get("min", 0)), _number(opts.get("max", 100))
    if lo is None or hi is None:
        return ["'min' and 'max' must be numbers"]
    return ["'max' must be above 'min'"] if hi <= lo else []


def _arc_point(fraction: float, radius: float) -> tuple[float, float]:
    """A point on the dial, 0 at the left end, 1 at the right, over the top;
    the dial's centre is (50, 50) in the card's SVG units."""
    angle = math.pi * (1 - fraction)
    return 50 + radius * math.cos(angle), 50 - radius * math.sin(angle)


def build_gauge(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The stat as a dial: the value's share of ``min``…``max`` as a filled
    arc, a needle, and the card's colour rules drawn as bands under the arc
    (a rule's range clipped to the dial), so the number's state is visible as
    where the needle sits. Tapping it opens the rows, like a stat."""
    metric = ctx.metric
    assert metric is not None
    opts = cell.get("options") or {}
    # `or` would turn a floor or ceiling of 0 into the default: a dial from -100 to 0 drew to 100.
    lo, hi = _number(opts.get("min", 0)), _number(opts.get("max", 100))
    lo, hi = (0.0 if lo is None else lo), (100.0 if hi is None else hi)
    label = cell_title(cell) or metric.name
    card = metric_card_context(
        metric, ctx.request, period=ctx.period, label=label, period_in_label=False, rows=ctx.rows_url
    )
    result = card["result"]
    style = card_style(cell)
    context: dict[str, Any] = {"card": card, "result": result, "style": style, "label": label, "lo": lo, "hi": hi}
    context["lo_display"] = styled_value(lo, metric, style, None)["display"]
    context["hi_display"] = styled_value(hi, metric, style, None)["display"]
    if result.ok:
        shown = styled_value(result.value, metric, style, result.state)
        card.update(value=shown["display"], unit=shown["unit"], state=shown["state"])
    card["href"] = rows_url(ctx, **drill_params(cell)) if card.get("href") else ""
    value = _number(result.value) if result.ok else None
    fraction = min(1.0, max(0.0, (value - lo) / (hi - lo))) if value is not None else 0.0
    x, y = _arc_point(fraction, 34)
    context.update({"fraction": f"{fraction * 100:.2f}", "needle_x": f"{x:.2f}", "needle_y": f"{y:.2f}"})
    # The rules as bands: each rule's range on the dial, in the state's colour.
    rules = style["thresholds"] if style["thresholds"] is not None else (metric.thresholds or [])
    bands = []
    for rule in rules if isinstance(rules, list) else []:
        if not isinstance(rule, dict) or rule.get("state") not in ("success", "warning", "danger", "muted"):
            continue
        op, target = rule.get("op"), rule.get("value")
        if op == "between" and isinstance(target, list) and len(target) == 2:
            start, end = _number(target[0]), _number(target[1])
        elif op in (">", ">="):
            start, end = _number(target), hi
        elif op in ("<", "<="):
            start, end = lo, _number(target)
        else:
            continue
        if start is None or end is None:
            continue
        a, b = max(lo, min(hi, start)), max(lo, min(hi, end))
        if b > a:
            bands.append(
                {
                    "state": rule["state"],
                    "start": f"{(a - lo) / (hi - lo) * 100:.2f}",
                    "length": f"{(b - a) / (hi - lo) * 100:.2f}",
                }
            )
    context["bands"] = bands
    return context


# -- table: the filtered rows themselves, paged, sorted by their headers --------------

NUMBER_TYPES = ("integer", "float", "decimal")


def validate_table(cell: dict[str, Any]) -> list[str]:
    opts = cell.get("options") or {}
    problems = []
    rows = opts.get("rows", 10)
    if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= 100:
        problems.append("'rows' (a page's rows) must be 1–100")
    if "totals" in opts and not isinstance(opts["totals"], bool):
        problems.append("'totals' must be true or false")
    return problems


def _table_sort(request: HttpRequest, columns: list[dict[str, Any]], current: str, pageable: bool) -> None:
    """Each header's link: the same card ordered by that column (a second
    click flips it; dates and numbers start largest first, text A–Z). The
    link is this cell's own URL, which htmx swaps in place."""
    params = request.GET.copy()
    params.pop("page", None)
    for c in columns:
        name = c["name"]
        if current == name:
            c["aria_sort"], nxt = "ascending", f"-{name}"
        elif current == f"-{name}":
            c["aria_sort"], nxt = "descending", name
        else:
            c["aria_sort"], nxt = "none", f"-{name}" if c.get("type") in ("date", "datetime", *NUMBER_TYPES) else name
        params["order"] = nxt
        c["sort_url"] = f"{request.path}?{params.urlencode()}" if pageable else ""


def build_table(cell: dict[str, Any], ctx: CellContext) -> dict[str, Any]:
    """The rows the card's filter selects, a page at a time, in the columns of
    its drill-down design (the data's first columns without one). ``?order=``
    and ``?page=`` on the cell's own URL sort and page it in place; ``totals``
    adds a footer of sums over every matching row for the number columns."""
    metric = ctx.metric
    assert metric is not None
    opts = cell.get("options") or {}
    raw_rows = opts.get("rows")
    per_page = min(100, max(1, raw_rows if isinstance(raw_rows, int) and not isinstance(raw_rows, bool) else 10))
    label = cell_title(cell) or metric.name
    context: dict[str, Any] = {"label": label, "columns": [], "rows": [], "total": 0, "per_page": per_page}
    if not may_read(metric, getattr(ctx.request, "user", None)):
        return {**context, "restricted": True}
    ds = resolve_dataset(metric)
    if ds is None:
        return {**context, "error": "This card's data isn't available."}
    spec = opts.get("drilldown") if isinstance(opts.get("drilldown"), dict) else None
    if spec is not None and validate_drilldown(spec, ds.column_names()):
        return {**context, "error": "The card's columns no longer fit its data. Edit the card to choose them again."}
    # The design's own row limit is for the window its rows open in; the card pages.
    spec = {k: v for k, v in spec.items() if k != "limit"} if spec else None
    order = str(ctx.request.GET.get("order") or "")
    if order.lstrip("-") not in ds.column_names():
        order = ""
    try:
        page = max(1, int(ctx.request.GET.get("page") or 1))
    except ValueError:
        page = 1
    try:
        drill = drill_rows(
            metric, ctx.request, period=ctx.period, spec=spec, order=order, limit=per_page, offset=(page - 1) * per_page
        )
    except (FilterTreeError, ValueError) as exc:
        return {**context, "error": str(exc)}
    total = drill["total"]
    pages = max(1, math.ceil(total / per_page))
    if page > pages:  # past the end (rows went away): the last page, not an empty one
        page = pages
        drill = drill_rows(
            metric, ctx.request, period=ctx.period, spec=spec, order=order, limit=per_page, offset=(page - 1) * per_page
        )
    # In place only where the cell has a URL of its own (on a dashboard; not the builder's preview).
    pageable = ctx.dashboard is not None and ctx.dashboard.pk is not None and bool(cell.get("id"))
    _table_sort(ctx.request, drill["columns"], drill.get("sort") or "", pageable)
    params = ctx.request.GET.copy()
    links = {}
    for key, n in (("prev", page - 1), ("next", page + 1)):
        params["page"] = str(n)
        links[key] = f"{ctx.request.path}?{params.urlencode()}" if pageable and 1 <= n <= pages else ""
    columns = drill["columns"]
    for c in columns:
        c["num"] = c.get("type") in NUMBER_TYPES  # right-aligned, like the totals under it
    totals: list[Any] = []
    if opts.get("totals"):
        totals = [{"v": v, "num": c["num"]} for v, c in zip(_column_totals(ds, metric, ctx, columns), columns)]
    rows = [
        {"url": r.get("url"), "cells": [{"v": v, "num": c["num"]} for v, c in zip(r["cells"], columns)]}
        for r in drill["rows"]
    ]
    first = (page - 1) * per_page + 1 if total else 0
    return {
        **context,
        "columns": columns,
        "rows": rows,
        "total": total,
        "page": page,
        "pages": pages,
        "first": first,
        "last": min(total, page * per_page),
        "prev_url": links["prev"],
        "next_url": links["next"],
        "totals": totals,
        "all_url": rows_url(ctx, **drill_params(cell)),
        "cell_id": cell.get("id") or "card",
    }


def _column_totals(ds: Any, metric: Any, ctx: CellContext, columns: list[dict[str, Any]]) -> list[Any]:
    """One footer cell per column: the sum over every matching row for a
    number column (a ratio measure has no sum), blank for the rest; nothing
    at all if the sums can't be asked for."""
    declared = ds.declared_measures()
    wanted = [c for c in columns if c.get("type") in NUMBER_TYPES and c["name"] not in declared]
    if not wanted:
        return []
    try:
        qs = ds.queryset(ctx.request, filter_tree=effective_tree(metric, ctx.period))
        sums = qs.aggregate(**{f"t_{c['name']}": Sum(c["name"]) for c in wanted})
    except Exception:  # noqa: BLE001 — a column that can't be summed: no footer, not a broken card
        return []
    by_name = {c["name"]: sums.get(f"t_{c['name']}") for c in wanted}
    return [
        format_cell(by_name[c["name"]], c.get("format") or "number", c.get("type") or "")
        if c["name"] in by_name
        else ""
        for c in columns
    ]


def register() -> None:
    register_component_type(
        ComponentType(
            key="bars",
            label="Bar chart",
            description=(
                "Filtered rows split by a column, as columns or bars: largest first, or by name. "
                "Each one opens its rows."
            ),
            group="Charts",
            stylable=True,
            drillable=True,
            icon="M3 20V10h4v10H3zm7 0V4h4v16h-4zm7 0v-7h4v7h-4z",
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/bars.html",
            build=build_bars,
            needs_metric=True,
            default_size=(4, 3),
            requires=frozenset({"dimension"}),
            validate=validate_bars,
            options_schema=[
                *_group_options(8),
                {
                    "name": "direction",
                    "label": "Draw as",
                    "type": "choice",
                    "choices": list(DIRECTIONS),
                    "default": "vertical",
                    "widget": "segmented",
                },
                {
                    "name": "order",
                    "label": "Order",
                    "type": "choice",
                    "choices": list(ORDERS),
                    "default": "value",
                    "widget": "segmented",
                },
            ],
        )
    )
    register_component_type(
        ComponentType(
            key="gauge",
            label="Gauge",
            description=(
                "One number on a dial between a floor and a ceiling, its colour rules as bands; click for rows."
            ),
            group="Stats",
            stylable=True,
            drillable=True,
            single_value=True,
            icon=(
                "M12 4a10 10 0 0 0-10 10h2a8 8 0 0 1 16 0h2A10 10 0 0 0 12 4z"
                "m-1 10.5 4.3-6.1 1.6 1.2-4.3 6a1.5 1.5 0 1 1-1.6-1.1z"
            ),
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/gauge.html",
            build=build_gauge,
            needs_metric=True,
            default_size=(3, 2),
            validate=validate_gauge,
            options_schema=[
                {"name": "min", "label": "Floor", "type": "number", "default": 0, "help": "The dial's left end."},
                {"name": "max", "label": "Ceiling", "type": "number", "default": 100, "help": "The dial's right end."},
            ],
        )
    )
    register_component_type(
        ComponentType(
            key="table",
            label="Table",
            description=(
                "The filtered rows themselves, a page at a time: your columns, headings and formats; "
                "sortable by header; totals for number columns."
            ),
            group="Charts",
            drillable=True,
            shows_rows=True,
            icon="M3 4h18v16H3V4zm2 2v3h14V6H5zm0 5v3h6v-3H5zm8 0v3h6v-3h-6zm-8 5v3h6v-3H5zm8 0v3h6v-3h-6z",
            media={"css": ["website/css/dashboard-cards.css"]},
            template="website/cells/table.html",
            build=build_table,
            needs_metric=True,
            default_size=(6, 4),
            validate=validate_table,
            options_schema=[
                {"name": "rows", "label": "Rows a page", "type": "integer", "default": 10, "min": 1, "max": 100},
                {"name": "totals", "label": "Totals for number columns", "type": "boolean", "default": False},
            ],
        )
    )
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
            description="Filtered rows split by a column: the groups as bars, largest first. Each one opens its rows.",
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
            description="Filtered rows over time — bars or a line per day, week or month. Each bucket opens its rows.",
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
                {
                    "name": "kind",
                    "label": "Chart",
                    "type": "choice",
                    "choices": list(KINDS),
                    "default": "bars",
                    "widget": "segmented",
                },
                {
                    "name": "grain",
                    "label": "Buckets",
                    "type": "choice",
                    "choices": list(GRAIN_CHOICES),
                    "default": "",
                    "widget": "segmented",
                    "help": "Buckets by the card's period column. Fit: days for a month, weeks for a season, months "
                    "for a year or two, quarters beyond; over all time, fitted to the span of the data.",
                },
            ],
        )
    )
