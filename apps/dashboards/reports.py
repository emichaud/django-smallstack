"""Reports — metrics as rows, periods as columns.

- :func:`report_matrix` — the raw matrix: every row's ``MetricResult`` per
  column. The CSV and the REST/MCP values read this.
- :func:`present_report` — the matrix shaped for reading: headings, a lede,
  each first value's change from the second column, a drill-down per value,
  one merged cell for a metric that doesn't depend on time.
- :func:`report_values` — the JSON shape REST and MCP return.
- :func:`write_report_csv` — the matrix as CSV into any file-like object.
- :func:`report_movement` — how many rows went up / down / held between the
  first two columns (the reports list's one-line digest).

Every function takes the ``request`` whose user the numbers are for (the
evaluation seam's access rule); none renders HTML.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest
from django.urls import reverse

from apps.datasets.core import SafeCsvWriter
from apps.datasets.dateranges import period_label

from .comparison import delta
from .goals import STATUS_LABELS, STATUS_STATES, judge, rule_text
from .metrics import evaluate
from .models import Metric, Report
from .periods import TO_DATE_PERIODS, join_words, period_heading, plain_reading

if TYPE_CHECKING:
    from _typeshed import SupportsWrite


def report_matrix(report: Report, request: HttpRequest) -> dict[str, Any]:
    """``{columns: [{key, label}], rows: [{label, metric, cells: [{result, na}]}], has_targets}``.

    A row with a ``target`` (and optionally ``warn``, the at-risk line — the
    goal rules, ``goals.judge``) adds ``target``, ``warn``, ``target_text`` and
    ``warn_text``, and each of its cells a ``status`` (pass / warn / fail /
    none); the value's colour then comes from that status, not the metric's
    colour rules. A metric that isn't period-aware is evaluated once (period-free) and its
    other columns marked ``na``, rather than repeating one number under
    several headings as though it varied. A row whose metric was deleted has
    ``missing: True`` and no cells."""
    periods = report.periods or []
    columns = [{"key": p, "label": period_label(p)} for p in periods] or [{"key": "", "label": "All time"}]
    metrics = {m.key: m for m in Metric.objects.filter(key__in=report.metric_keys())}
    rows: list[dict[str, Any]] = []
    for item in report.items:
        metric = metrics.get(item.get("metric", ""))
        label = item.get("label") or (metric.name if metric else item.get("metric"))
        if metric is None:
            rows.append({"label": label, "metric": None, "missing": True, "cells": []})
            continue
        cells: list[dict[str, Any]] = []
        if not metric.period_field and periods:
            first = evaluate(metric, request)
            cells = [{"result": first, "na": False}] + [{"result": None, "na": True} for _ in periods[1:]]
        else:
            for col in columns:
                cells.append({"result": evaluate(metric, request, period=col["key"] or None), "na": False})
        row: dict[str, Any] = {"label": label, "metric": metric, "cells": cells}
        target, warn = item.get("target"), item.get("warn")
        if target:
            row.update(
                target=target,
                warn=warn,
                target_text=rule_text(target, metric.format, metric.unit),
                warn_text=rule_text(warn, metric.format, metric.unit),
            )
            for cell in cells:
                result = cell["result"]
                if result is None:
                    continue
                status = judge(result.value, target, warn) if result.ok else "none"
                cell["status"], cell["status_label"] = status, STATUS_LABELS[status]
                if result.ok:
                    result.state = STATUS_STATES[status]
        rows.append(row)
    return {"columns": columns, "rows": rows, "has_targets": any(r.get("target") for r in rows)}


def present_report(matrix: dict[str, Any]) -> dict[str, Any]:
    """Shape a :func:`report_matrix` for reading. Adds to each column a
    ``heading``; to each row a ``reading`` (its filter in prose), ``drills``
    (``{url, title}`` per value — the rows behind it, or None), and either
    ``delta`` (first column against the second) or ``span`` (the one value of
    a metric that doesn't depend on time). Returns ``{columns, rows, lede,
    compare, partial}`` — ``partial`` when the first column is still running,
    so every change compares part of a period with all of the last."""
    columns = [{**c, "heading": period_heading(c["key"])} for c in matrix["columns"]]
    compare = len(columns) > 1
    partial = compare and columns[0]["key"] in TO_DATE_PERIODS
    rows = []
    for row in matrix["rows"]:
        out = dict(row)
        metric = row.get("metric")
        cells = row.get("cells") or []
        if metric is not None:
            out["reading"] = plain_reading(metric.filter_summary)
            out["drills"] = _drills(metric, row["label"], columns, cells)
        if compare and cells and all(c["na"] for c in cells[1:]):
            out["span"] = cells[0]["result"]
            out["span_drill"] = (out.get("drills") or [None])[0]
        elif compare and len(cells) > 1:
            against = columns[1]["heading"].lower()
            out["delta"] = delta(cells[0]["result"], cells[1]["result"], f"all of {against}" if partial else against)
        rows.append(out)
    n = len(rows)
    metrics = f"{n} metric{'s' if n != 1 else ''}"
    if compare:
        lede = f"{metrics}, compared across {join_words([c['heading'].lower() for c in columns])}."
    else:
        lede = f"{metrics}, {columns[0]['heading'].lower()}."
    return {
        "columns": columns,
        "rows": rows,
        "lede": lede,
        "compare": compare,
        "partial": partial,
        "has_targets": bool(matrix.get("has_targets")),
    }


def _drills(metric: Metric, label: str, columns: list[dict[str, Any]], cells: list[dict[str, Any]]) -> list[Any]:
    """Per value, the rows behind it for that column's period (or the whole
    metric, for one without a period field); None where there's no number."""
    base = reverse("dashboards_metric_rows", kwargs={"key": metric.key})
    out: list[Any] = []
    for col, cell in zip(columns, cells):
        result = cell.get("result")
        if cell["na"] or result is None or not result.ok:
            out.append(None)
            continue
        key = col["key"] if metric.period_field else ""
        where = col["heading"].lower() if key else ""
        out.append(
            {"url": f"{base}?period={key}" if key else base, "title": f"{label}, {where}" if where else str(label)}
        )
    return out


def report_values(report: Report, request: HttpRequest) -> dict[str, Any]:
    """The report as JSON: ``{slug, name, columns, rows: [{label, metric,
    values: [result dict | null]}]}`` — what REST and MCP return."""
    matrix = report_matrix(report, request)
    rows = []
    for row in matrix["rows"]:
        if row.get("missing"):
            rows.append({"label": row["label"], "error": "metric no longer exists"})
            continue
        values: list[dict[str, Any] | None] = []
        for c in row["cells"]:
            if c["na"] or c["result"] is None:
                values.append(None)
                continue
            value = c["result"].as_dict()
            if "status" in c:
                value["status"] = c["status"]
            values.append(value)
        entry: dict[str, Any] = {"label": row["label"], "metric": row["metric"].key, "values": values}
        if row.get("target"):
            entry.update(target=row["target"], warn=row.get("warn"), target_text=row["target_text"])
        rows.append(entry)
    return {"slug": report.slug, "name": report.name, "columns": matrix["columns"], "rows": rows}


def report_order(raw: Any, matrix: dict[str, Any]) -> str:
    """A valid row order for *matrix* from ``?order=``, else "" (the report's
    own order): ``metric`` / ``-metric`` (by label), or ``c<i>`` / ``-c<i>``
    (by the value in column *i*)."""
    order = str(raw or "").strip()
    key = order.lstrip("-")
    if key == "metric":
        return order
    if key.startswith("c") and key[1:].isdigit() and int(key[1:]) < len(matrix["columns"]):
        return order
    return ""


def _sort_value(row: dict[str, Any], col: int) -> Optional[float]:
    cells = row.get("cells") or []
    if not cells:
        return None
    # A metric that doesn't depend on time has one value for every column.
    cell = cells[0] if all(c["na"] for c in cells[1:]) else (cells[col] if col < len(cells) else None)
    result = cell and cell["result"]
    if result is None or not result.ok or isinstance(result.value, bool):
        return None
    return float(result.value) if isinstance(result.value, (int, float)) else None


def sort_report(matrix: dict[str, Any], order: str) -> dict[str, Any]:
    """*matrix* with its rows in *order* (:func:`report_order`). Rows with no
    number to sort by — a deleted metric, restricted, an error — always go
    last, whichever the direction."""
    if not order:
        return matrix
    desc, key = order.startswith("-"), order.lstrip("-")
    rows = list(matrix["rows"])
    if key == "metric":
        rows.sort(key=lambda r: str(r.get("label") or "").lower(), reverse=desc)
    else:
        col = int(key[1:])
        have = [r for r in rows if _sort_value(r, col) is not None]
        rest = [r for r in rows if _sort_value(r, col) is None]
        have.sort(key=lambda r: _sort_value(r, col) or 0.0, reverse=desc)
        rows = have + rest
    return {**matrix, "rows": rows}


def report_sort_links(matrix: dict[str, Any], order: str) -> list[dict[str, Any]]:
    """Per header (Metric, then each column): ``{key, aria_sort, next}`` —
    the ``?order=`` a click asks for. Metric starts A–Z, numbers largest
    first; a second click flips it."""
    keys = ["metric", *[f"c{i}" for i in range(len(matrix["columns"]))]]
    out = []
    for key in keys:
        if order == key:
            aria, nxt = "ascending", f"-{key}"
        elif order == f"-{key}":
            aria, nxt = "descending", key
        else:
            aria, nxt = "none", key if key == "metric" else f"-{key}"
        out.append({"key": key, "aria_sort": aria, "next": nxt})
    return out


def write_report_csv(matrix: dict[str, Any], out: "SupportsWrite[str]") -> None:
    """Write a :func:`report_matrix` as CSV to *out* (an ``HttpResponse``
    works). Raw values, not formatted; problems are spelled out in the cell."""
    writer = SafeCsvWriter(out)
    targets = bool(matrix.get("has_targets"))
    head = ["Metric", *(["Target", "At risk"] if targets else [])]
    for c in matrix["columns"]:
        head += [c["label"], *([f"{c['label']} status"] if targets else [])]
    writer.writerow(head)
    for row in matrix["rows"]:
        lead = [row["label"], *([row.get("target_text", ""), row.get("warn_text", "")] if targets else [])]
        if row.get("missing"):
            missing = [["(missing metric)", *([""] if targets else [])] for _ in matrix["columns"]]
            writer.writerow([*lead, *[v for pair in missing for v in pair]])
            continue
        values: list[Any] = []
        for cell in row["cells"]:
            result = cell["result"]
            if cell["na"] or result is None:
                values.append("")
            elif result.restricted:
                values.append("(restricted)")
            elif result.error:
                values.append(f"(error: {result.error})")
            else:
                values.append(result.value if result.value is not None else "")
            if targets:
                values.append(cell.get("status_label", "") if not cell["na"] else "")
        writer.writerow([*lead, *values])


def sort_by_movement(reports: list[Report], request: HttpRequest, *, desc: bool = False) -> list[tuple[Report, Any]]:
    """*reports* ordered by how their rows moved between their first two
    columns: ``[(report, movement)]`` (:func:`report_movement`). Ascending puts
    the most fallen first (rows up minus rows down, then most rows down);
    descending the most risen. Reports with nothing to compare go last
    either way. Evaluates every report — the cost of sorting by it."""
    scored = [(r, report_movement(r, request)) for r in reports]
    have = [(r, m) for r, m in scored if m and m["compared"]]
    rest = [(r, m) for r, m in scored if not (m and m["compared"])]

    def key(pair: tuple[Report, Any]) -> tuple[int, int]:
        counts = pair[1]["counts"]
        return (counts["up"] - counts["down"], -counts["down"] if not desc else counts["up"])

    have.sort(key=key, reverse=desc)
    rest.sort(key=lambda pair: pair[0].name.lower())
    return have + rest


def report_movement(report: Report, request: HttpRequest) -> dict[str, Any] | None:
    """How the report's rows moved between its first two columns:
    ``{counts: {up, down, flat}, first, against, compared}``, or None for a
    report with fewer than two columns. Evaluates only those two columns."""
    if len(report.periods or []) < 2:
        return None
    pair = Report(name=report.name, items=report.items, periods=list(report.periods[:2]))
    shown = present_report(report_matrix(pair, request))
    counts = {"up": 0, "down": 0, "flat": 0}
    for row in shown["rows"]:
        if row.get("delta"):
            counts[row["delta"]["dir"]] += 1
    first, second = (c["heading"].lower() for c in shown["columns"][:2])
    return {
        "counts": counts,
        "first": first,
        "against": f"all of {second}" if shown["partial"] else second,
        "compared": sum(counts.values()),
    }
