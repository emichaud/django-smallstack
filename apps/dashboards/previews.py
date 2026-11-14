"""Dry runs — evaluate a metric or a report that hasn't been saved.

The metric builder, the report form and an agent iterating over MCP all
preview the same way: build an unsaved model instance, validate it exactly as
saving would, then run it through the ordinary evaluation path. Nothing here
writes to the database.
"""

from __future__ import annotations

from typing import Any, Optional

from django.core.exceptions import ValidationError
from django.http import HttpRequest

from apps.datasets.core import get_dataset
from apps.datasets.dateranges import is_period
from apps.datasets.registry import get_def, user_may_read

from .metrics import FORMATS, all_aggs_available, effective_tree, evaluate, request_for
from .models import SOURCE_DATASET, SOURCE_RATE, SOURCES, Metric, Report
from .periods import NO_PERIOD_FIELD_NOTE, period_problem
from .reports import present_report, report_matrix


def unsaved_metric(user: Any, payload: dict[str, Any]) -> tuple[Optional[Metric], list[str]]:
    """A ``Metric`` built from *payload* without saving it, plus every
    validation problem (``"field: message"``). The metric is None when its
    dataset is unknown to *user* — an unreadable dataset is reported as
    unknown, so a preview never confirms that it exists."""
    source = str(payload.get("source") or SOURCE_DATASET)
    if source not in {key for key, _label in SOURCES}:
        return None, [f"source: use one of {[key for key, _label in SOURCES]}"]
    key = str(payload.get("dataset") or "")
    dfn = get_def(key)
    if source == SOURCE_DATASET and (dfn is None or not user_may_read(dfn, user)):
        return None, [f"unknown dataset {key!r} — list the datasets you may use first"]
    metric = Metric(
        key="preview",
        name=str(payload.get("name") or "Preview"),
        source=source,
        numerator=str(payload.get("numerator") or ""),
        denominator=str(payload.get("denominator") or ""),
        owner=user if payload.get("visibility") != "shared" and getattr(user, "pk", None) else None,
        dataset=key,
        filter_tree=payload.get("filter_tree") or {},
        agg=str(payload.get("agg") or "count"),
        measure=str(payload.get("measure") or ""),
        period_field=str(payload.get("period_field") or ""),
        format=str(payload.get("format") or "number"),
        unit=str(payload.get("unit") or ""),
        thresholds=payload.get("thresholds") or [],
    )
    problems: list[str] = []
    try:
        metric.clean()
    except ValidationError as exc:
        for field, messages in exc.message_dict.items():
            problems.extend(f"{field}: {m}" for m in messages)
    if source == SOURCE_RATE:
        for side in (metric.numerator, metric.denominator):
            part = Metric.objects.filter(key=side).first()
            if side and (part is None or not part.can_view(user)):
                # A key you can't open reads as unknown, as an unreadable dataset does.
                problems.append(f"no metric {side!r} — list the metrics you may use first")
    for name, vocabulary in (("agg", all_aggs_available()), ("format", FORMATS)):
        allowed = [c for c, _label in vocabulary]
        if getattr(metric, name) not in allowed:
            problems.append(f"{name}: use one of {allowed}")
    return metric, problems


def preview_metric(user: Any, payload: dict[str, Any], *, request: Optional[HttpRequest] = None) -> dict[str, Any]:
    """Evaluate the unsaved metric *payload* describes: ``{ok, problems,
    result, row_count}``. ``problems`` lists every validation issue at once,
    so a builder or an agent can fix them all in one round trip. *request*
    defaults to a synthetic one for *user* (MCP has no HTTP request)."""
    metric, problems = unsaved_metric(user, payload)
    period = payload.get("period") or None
    period_issue = period_problem(period)
    if period_issue:
        problems = [*problems, f"period: {period_issue}"]
    if metric is None or problems:
        return {"ok": False, "problems": problems}
    req = request if request is not None else request_for(user)
    result = evaluate(metric, req, period=str(period) if period else None)
    out: dict[str, Any] = {"ok": result.ok, "problems": result.problems, "result": result.as_dict()}
    if period and period != "all" and not metric.period_field:
        out["note"] = NO_PERIOD_FIELD_NOTE
    if result.ok:
        ds = get_dataset(metric.dataset)
        if ds is not None:
            out["row_count"] = ds.count(req, filter_tree=effective_tree(metric, result.period))
    return out


def preview_report(user: Any, payload: dict[str, Any], *, request: Optional[HttpRequest] = None) -> dict[str, Any]:
    """Evaluate an unsaved report ``{items, periods}`` — the same matrix and
    presentation as the report page, as JSON: ``{columns: [{key, heading}],
    rows: [{label, metric, period_aware, cells, delta, missing}], lede,
    partial}``. Items naming a metric *user* may not open are dropped;
    unknown periods are ignored."""
    raw = payload.get("items")
    items = []
    for i in (raw if isinstance(raw, list) else [])[: Report.MAX_ITEMS]:
        item = {"metric": i} if isinstance(i, str) else i
        if isinstance(item, dict) and isinstance(item.get("metric"), str):
            items.append({"metric": item["metric"], **({"label": item["label"]} if item.get("label") else {})})
    periods = [p for p in (payload.get("periods") or []) if isinstance(p, str) and is_period(p)][: Report.MAX_PERIODS]
    visible = set(
        Metric.objects.visible_to(user).filter(key__in=[i["metric"] for i in items]).values_list("key", flat=True)
    )
    report = Report(name="preview", items=[i for i in items if i["metric"] in visible], periods=periods)
    shown = present_report(report_matrix(report, request if request is not None else request_for(user)))
    rows = []
    for row in shown["rows"]:
        if row.get("span") is not None:
            cells = [{"span": True, **row["span"].as_dict()}]
        else:
            cells = [{"na": True} if c["na"] or c["result"] is None else c["result"].as_dict() for c in row["cells"]]
        metric = row.get("metric")
        rows.append(
            {
                "label": row["label"],
                "metric": metric.key if metric is not None else None,
                "period_aware": bool(metric is not None and metric.period_field),
                "cells": cells,
                "delta": row.get("delta"),
                "missing": bool(row.get("missing")),
            }
        )
    return {
        "columns": [{"key": c["key"], "heading": c["heading"]} for c in shown["columns"]],
        "rows": rows,
        "lede": shown["lede"],
        "partial": shown["partial"],
    }


def preview_card(user: Any, payload: dict[str, Any], request: HttpRequest) -> dict[str, Any]:
    """Render an UNSAVED card — the component builder's live preview, and a
    dry run for agents: ``{type, metric? | dataset + filter_tree + agg/measure/
    period_field, options?, name?, period?, visibility?}``
    → ``{"html", "problems"}``. Validated exactly as a dashboard cell is, and
    drawn by the same ``render_cell`` a dashboard uses, so the preview is the
    card. ``visibility="shared"`` checks it as a shared card would be."""
    from .boards import render_cell
    from .components import SOURCE_KEYS, normalize_layout
    from .models import Dashboard

    owner_id = None if payload.get("visibility") == "shared" else getattr(user, "pk", None)
    cell: dict[str, Any] = {"id": "preview", "type": payload.get("type"), "options": payload.get("options") or {}}
    if payload.get("metric"):
        cell["metric"] = payload["metric"]
    elif payload.get("dataset"):
        cell.update({k: payload.get(k) for k in SOURCE_KEYS if payload.get(k) not in (None, "")})
    layout, problems = normalize_layout([cell], owner_id=owner_id)
    if problems:
        return {"html": "", "problems": [p.replace("layout[0]", "card").replace("card: ", "") for p in problems]}
    placed = {**layout[0], "name": payload.get("name") or ""}
    period = payload.get("period") or None
    if period and period != "all" and not is_period(period):
        return {"html": "", "problems": [f"{period!r} is not a known period"]}
    board = Dashboard(name="Preview", slug="preview", owner_id=owner_id)
    return {"html": render_cell(board, placed, request, None if period == "all" else period), "problems": []}
