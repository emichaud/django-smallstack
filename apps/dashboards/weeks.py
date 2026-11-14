"""Weeks — a goal list week by week, the way a spreadsheet keeps a tab per week.

A week runs Monday to Sunday (local time). Each goal's value for a week is its
metric narrowed to that week's dates (``[Monday, next Monday)`` on the
metric's period field), judged against the goal's target. A metric without a
period field has one value whatever the week, so it's marked ``weekly: False``.

A **snapshot** (``snapshots.py``, the weekly cadence) keeps a week as it was: every goal's value,
status and the target it was judged against then. The hourly job (``snapshots.capture_due``)
saves the week just ended for every list tracking weeks;
anyone who can edit a list can take or retake one, or fill in past weeks.
Showing a week prefers its snapshot and otherwise works it out live, so the
current week, and weeks before snapshots started, still have numbers.

The building blocks:

- :func:`week_of` / :func:`parse_week` / :func:`week_label` — week arithmetic and words.
- :func:`weekly_values` — a metric per week over a run of weeks, one query.
- :func:`build_week` — a list's rows for one week, worked out now.
- :func:`take_snapshot` — save a week.
- :func:`week_page` — one week to read: snapshot or live, with last week's change.
- :func:`week_grid` — goals down, weeks across: the week-over-week table (and CSV).
- :func:`week_trends` — the weeks around one week, per goal: the trend button.

A snapshot is taken as the list's owner (a personal list) or the person who
made it (a shared one; the first active superuser if nobody did), so its
numbers are what that person may read. Whoever
views it later still only sees values from datasets they may read.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from django.http import HttpRequest
from django.utils import timezone

from apps.datasets.core import SafeCsvWriter

from .goals import (
    STATUS_LABELS,
    STATUS_STATES,
    gap_text,
    goal_at,
    goal_lookups,
    goal_source,
    judge,
    rule_text,
    summarize,
)
from .metrics import (
    _is_number,
    display_unit,
    format_value,
    manual_buckets,
    may_read,
    rate_parts,
    rate_value,
    resolve_dataset,
)

if TYPE_CHECKING:
    from _typeshed import SupportsWrite

    from .models import GoalList, Metric, Snapshot

logger = logging.getLogger(__name__)

#: Weeks the grid shows, and the weeks either side of one the trends compare.
GRID_WEEKS = 8
TREND_BEFORE = 4
TREND_AFTER = 4
#: The row's Trends button: one goal over this many weeks.
GOAL_TREND_WEEKS = 13
#: The most past weeks one "fill in" request snapshots.
_ADDITIVE = frozenset({"count", "distinct", "sum"})
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# -- week arithmetic ---------------------------------------------------------------


def today() -> date:
    now = timezone.now()
    return timezone.localtime(now).date() if timezone.is_aware(now) else now.date()


def week_of(day: date) -> date:
    """The Monday of *day*'s week."""
    return day - timedelta(days=day.weekday())


def this_week() -> date:
    return week_of(today())


def parse_week(raw: Any) -> Optional[date]:
    """A week from ``2026-11-03`` (any day of it) or ``2026-W45``; ``None`` if
    neither."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if "W" in text.upper():
            year, week = text.upper().split("-W")
            return date.fromisocalendar(int(year), int(week), 1)
        return week_of(date.fromisoformat(text[:10]))
    except ValueError:
        return None


def span_label(start: date, end: date) -> str:
    """ "Nov 3 – 9, 2026", "Oct 27 – Nov 2, 2026", "Dec 29, 2025 – Jan 4, 2026"."""
    if start.year != end.year:
        return f"{_MONTHS[start.month - 1]} {start.day}, {start.year} – {_MONTHS[end.month - 1]} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{_MONTHS[start.month - 1]} {start.day} – {_MONTHS[end.month - 1]} {end.day}, {end.year}"
    return f"{_MONTHS[start.month - 1]} {start.day} – {end.day}, {end.year}"


def week_label(start: date) -> str:
    """ "Nov 3 – 9, 2026", "Oct 27 – Nov 2, 2026", "Dec 29, 2025 – Jan 4, 2026"."""
    return span_label(start, start + timedelta(days=6))


def week_short(start: date) -> str:
    """ "Nov 3" — a column heading."""
    return f"{_MONTHS[start.month - 1]} {start.day}"


def week_range(start: date) -> str:
    """ "Nov 3–9", "Oct 27 – Nov 2" — the grid's column heading: both ends of
    the week, no year (the picker carries that)."""
    end = start + timedelta(days=6)
    if start.month != end.month:
        return f"{_MONTHS[start.month - 1]} {start.day} – {_MONTHS[end.month - 1]} {end.day}"
    return f"{_MONTHS[start.month - 1]} {start.day}–{end.day}"


def iso_week(start: date) -> str:
    year, week, _ = start.isocalendar()
    return f"{year}-W{week:02d}"


def week_state(start: date) -> str:
    """``past``, ``current`` (still running) or ``future``."""
    now = this_week()
    return "current" if start == now else ("past" if start < now else "future")


# -- values ----------------------------------------------------------------------


def weekly_values(metric: "Metric", request: HttpRequest, first: date, count: int) -> dict[str, Any]:
    """*metric* for each of *count* weeks from *first*: ``{values: {monday:
    value}, weekly, error, restricted}``. One query (the dataset's weekly
    series over the span). A week with no rows reads 0 for an additive
    aggregation and ``None`` otherwise; a metric without a period field has
    the same (all-time) value every week, with ``weekly: False``."""
    from apps.datasets.filter_tree import FilterTreeError, and_trees

    from .metrics import evaluate

    weeks = [first + timedelta(weeks=i) for i in range(count)]
    out: dict[str, Any] = {"values": {}, "weekly": bool(metric.period_field), "error": "", "restricted": False}
    if not may_read(metric, getattr(request, "user", None)):
        out["restricted"] = True
        return out
    if not metric.period_field:
        result = evaluate(metric, request)
        if not result.ok:
            out["error"] = result.error or "This metric could not be evaluated."
        out["values"] = {w: result.value for w in weeks} if result.ok else {}
        return out
    if metric.is_rate:
        return _weekly_rate(metric, request, first, count, out)
    ds = resolve_dataset(metric)
    if ds is None:
        out["error"] = f"Dataset “{metric.dataset}” is not available."
        return out
    span = and_trees(
        metric.filter_tree,
        {
            "and": [
                {"field": metric.period_field, "op": ">=", "value": first.isoformat()},
                {"field": metric.period_field, "op": "<", "value": (first + timedelta(weeks=count)).isoformat()},
            ]
        },
    )
    try:
        if metric.is_manual:
            by_week = manual_buckets(metric, request, span, week_of)
            out["values"] = {w: by_week.get(w) for w in weeks}
            return out
        rows = ds.series(
            metric.period_field,
            measure=metric.measure or None,
            agg=metric.agg or "count",
            grain="week",
            limit=count + 1,
            filter_tree=span,
            request=request,
        )
    except FilterTreeError:
        out["error"] = "This metric's filter no longer applies to its dataset."
        return out
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    except Exception:  # noqa: BLE001 — one broken metric must not take the week down
        logger.exception("weeks: metric %s failed", metric.key)
        out["error"] = "This metric could not be evaluated."
        return out
    by_start = {str(r["lo"])[:10]: r["value"] for r in rows}
    empty = 0 if (metric.agg or "count") in _ADDITIVE and metric.measure not in ds.declared_measures() else None
    out["values"] = {w: by_start.get(w.isoformat(), empty) for w in weeks}
    return out


def _weekly_rate(
    metric: "Metric", request: HttpRequest, first: date, count: int, out: dict[str, Any]
) -> dict[str, Any]:
    """A rate week by week: its parts' weekly values, divided. Each week is worked
    out from that week's two numbers, never by averaging rates."""
    numerator, denominator = rate_parts(metric)
    if numerator is None or denominator is None or bool(numerator.period_field) != bool(denominator.period_field):
        out["error"] = "This rate's two metrics can't be compared."
        return out
    top, bottom = weekly_values(numerator, request, first, count), weekly_values(denominator, request, first, count)
    out["restricted"] = top["restricted"] or bottom["restricted"]
    out["error"] = top["error"] or bottom["error"]
    if not out["restricted"] and not out["error"]:
        out["values"] = {w: rate_value(v, bottom["values"].get(w), metric.format) for w, v in top["values"].items()}
    return out


#: A value with nothing to judge it against, which isn't the same as no data.
NO_TARGET = "No target"


def _cell(
    goal: dict[str, Any], value: Any, src: dict[str, Any], *, error: str = "", restricted: bool = False
) -> dict[str, Any]:
    target = goal.get("target")
    status = judge(value, target, goal.get("warn")) if target and not (error or restricted) else "none"
    return {
        "value": float(value) if _is_number(value) and not isinstance(value, int) else value,
        "display": "—" if restricted or error or value is None else format_value(value, src["fmt"], src["unit"]),
        "unit": display_unit(src["fmt"], src["unit"]),
        "status": status,
        "status_label": NO_TARGET if not target and value is not None else STATUS_LABELS[status],
        "state": STATUS_STATES[status],
        "gap_text": gap_text(value, target, src["fmt"], src["unit"]) if status != "none" and target else "",
        "error": "You don't have access to this metric's data." if restricted else error,
        "restricted": restricted,
    }


def _goal_rows(goal_list: "GoalList") -> list[tuple[str, dict[str, Any]]]:
    return [
        (section.get("title", ""), goal)
        for section in goal_list.sections
        if isinstance(section, dict)
        for goal in section.get("goals", [])
        if isinstance(goal, dict)
    ]


def live_cells(
    goal_list: "GoalList", request: HttpRequest, first: date, count: int
) -> dict[str, dict[date, dict[str, Any]]]:
    """Every goal's cell for each of *count* weeks from *first*, worked out
    now: ``{goal_id: {monday: cell}}``. One series query per metric."""
    metrics, cards = goal_lookups(goal_list)
    series: dict[str, dict[str, Any]] = {}
    out: dict[str, dict[date, dict[str, Any]]] = {}
    weeks = [first + timedelta(weeks=i) for i in range(count)]
    for _title, goal in _goal_rows(goal_list):
        goal = goal_at(goal, "weekly", None)
        src = goal_source(goal, metrics, cards)
        metric = src["metric"]
        if metric is None:
            out[goal["id"]] = {w: _cell(goal, None, src, error="Its metric or card no longer exists.") for w in weeks}
            continue
        if metric.key not in series:
            series[metric.key] = weekly_values(metric, request, first, count)
        got = series[metric.key]
        out[goal["id"]] = {
            w: {
                **_cell(goal, got["values"].get(w), src, error=got["error"], restricted=got["restricted"]),
                "weekly": got["weekly"],
            }
            for w in weeks
        }
    return out


def goal_row(title: str, goal: dict[str, Any], src: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    """One goal for one period, exactly what a capture stores: ``{id, section, label,
    metric, component, datasets, value, display, unit, status, target, warn,
    target_text, warn_text, gap_text, note, error, weekly}``."""
    metric = src["metric"]
    return {
        "id": goal["id"],
        "section": title,
        "label": src["label"],
        "metric": goal.get("metric", ""),
        "component": goal.get("component", ""),
        "metric_key": metric.key if metric is not None else "",
        "dataset": metric.dataset if metric is not None else "",
        "datasets": metric.read_datasets() if metric is not None else [],
        "target": goal.get("target"),
        "warn": goal.get("warn"),
        "target_text": rule_text(goal.get("target"), src["fmt"], src["unit"]),
        "warn_text": rule_text(goal.get("warn"), src["fmt"], src["unit"]),
        "note": goal.get("note", ""),
        **{k: cell[k] for k in ("value", "display", "unit", "status", "gap_text", "error")},
        "weekly": cell.get("weekly", True),
    }


def build_week(goal_list: "GoalList", request: HttpRequest, start: date) -> list[dict[str, Any]]:
    """The list's rows for the week from *start*, worked out now (:func:`goal_row`)."""
    metrics, cards = goal_lookups(goal_list)
    cells = live_cells(goal_list, request, start, 1)
    return [
        goal_row(title, weekly, src, cells[goal["id"]][start])
        for title, goal in _goal_rows(goal_list)
        for weekly in [goal_at(goal, "weekly", None)]
        for src in [goal_source(goal, metrics, cards)]
    ]


def _json_safe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from decimal import Decimal

    out = []
    for row in rows:
        value = row.get("value")
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        out.append({**row, "value": value})
    return out


def snapshot_user(goal_list: "GoalList") -> Any:
    """Whose access a snapshot is taken with: the owner of a personal list,
    the person who made a shared one — or, for a shared list nobody made
    through the app (a seed, the shell), the first active superuser. ``None``
    only when there's no one at all."""
    from django.contrib.auth import get_user_model

    user = goal_list.owner or goal_list.created_by
    if user is None and goal_list.owner_id is None:
        user = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    return user


def _week_period(start: date) -> Any:
    from .snapshots import WEEKLY, _midnight, period_at

    return period_at(WEEKLY, _midnight(week_of(start)))


def weekly_captures(goal_list: "GoalList", weeks: list[date]) -> dict[date, "Snapshot"]:
    """``{monday: its newest weekly capture}``, for the weeks that have one."""
    from .snapshots import WEEKLY, latest_captures

    found = latest_captures(goal_list, WEEKLY, [_week_period(w) for w in weeks])
    return {s.week_start: s for s in found.values()}


def take_snapshot(goal_list: "GoalList", start: date, *, by: Any = None) -> "Snapshot":
    """Add a capture of the week from *start* (``snapshots.capture``). *by* is who
    asked (``None`` = the schedule). Refuses a week that hasn't started. A number that
    doesn't depend on time has no value for an old week, rather than today's: the same
    answer filling that week in gives."""
    from .snapshots import capture, last_closed

    period = _week_period(start)
    if period.state == "future":
        raise ValueError("That week hasn't started yet.")
    return capture(goal_list, period, by=by, past=period.start < last_closed(period.cadence).start)


def snapshot_last_week(*, lists: Optional[list["GoalList"]] = None) -> int:
    """The schedule's job: snapshot the week just ended for every goal list
    (or *lists*) whose owner or maker is still around. Returns how many."""
    from .models import GoalList

    start = this_week() - timedelta(weeks=1)
    done = 0
    for goal_list in lists if lists is not None else GoalList.objects.all():
        if snapshot_user(goal_list) is None or not goal_list.goals():
            continue
        try:
            take_snapshot(goal_list, start)
            done += 1
        except Exception:  # noqa: BLE001 — one list's failure must not stop the rest
            logger.exception("weeks: snapshot of %s for %s failed", goal_list.slug, start)
    return done


def backfill(goal_list: "GoalList", weeks: int, *, by: Any = None, replace: bool = False) -> int:
    """Capture the *weeks* past weeks (most recent first) that don't have one yet (or
    all of them with *replace*), judged against today's targets. Returns how many."""
    from .snapshots import WEEKLY, fill

    return fill(goal_list, WEEKLY, weeks, by=by, replace_existing=replace)


# -- reading weeks -----------------------------------------------------------------


def _viewer_may_read(dataset: str, user: Any, cache: dict[str, bool]) -> bool:
    from apps.datasets.registry import get_def, user_may_read

    if dataset not in cache:
        dfn = get_def(dataset) if dataset else None
        cache[dataset] = dfn is not None and user_may_read(dfn, user)
    return cache[dataset]


def _masked(rows: list[dict[str, Any]], user: Any) -> list[dict[str, Any]]:
    """Snapshot rows as *user* may see them: a value from a dataset they
    can't read is hidden (the snapshot was taken with someone else's access)."""
    cache: dict[str, bool] = {}
    out = []
    for row in rows:
        unjudged = not row.get("target") and row.get("value") is not None
        label = NO_TARGET if unjudged else STATUS_LABELS.get(row.get("status", "none"), "No data")
        row = {**row, "status_label": label}
        row["state"] = STATUS_STATES.get(row.get("status", "none"), "muted")
        # "datasets" is every dataset behind the number (a rate has two parts and
        # no dataset of its own); rows saved before it existed name just the one.
        sources = row.get("datasets") or ([row["dataset"]] if row.get("dataset") else [])
        if not all(_viewer_may_read(dataset, user, cache) for dataset in sources):
            row.update(value=None, display="—", status="none", status_label="No data", state="muted", gap_text="")
            row["error"], row["restricted"] = "You don't have access to this metric's data.", True
        out.append(row)
    return out


def _change(now: Any, before: Any, against: str = "the week before") -> Optional[dict[str, str]]:
    from .comparison import delta
    from .metrics import MetricResult

    if not (_is_number(now) and _is_number(before)):
        return None
    return delta(MetricResult(value=now, display=""), MetricResult(value=before, display=""), against)


def _sections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for row in rows:
        if not sections or sections[-1]["title"] != row.get("section", ""):
            sections.append({"title": row.get("section", ""), "rows": []})
        sections[-1]["rows"].append(row)
    for section in sections:
        section["summary"] = summarize(section["rows"])
    return sections


def _week_rows(
    goal_list: "GoalList", request: HttpRequest, start: date, snapshot: Optional["Snapshot"]
) -> list[dict[str, Any]]:
    if snapshot is not None:
        return _masked(snapshot.rows, request.user)
    return [
        {**row, "status_label": STATUS_LABELS[row["status"]], "state": STATUS_STATES[row["status"]]}
        for row in build_week(goal_list, request, start)
    ]


def _week_drill(row: dict[str, Any], start: date) -> Optional[dict[str, str]]:
    """The rows behind a week's value: the metric's rows modal narrowed to the
    week (``?narrow=``), or ``None`` without a number to open."""
    import json
    from urllib.parse import urlencode

    from django.urls import reverse

    from .models import Metric

    key = row.get("metric_key") or row.get("metric")
    if not key or row.get("error") or row.get("value") is None:
        return None
    metric = Metric.objects.filter(key=key).only("key", "period_field", "source").first()
    if metric is None or metric.is_rate:
        return None
    url = reverse("dashboards_metric_rows", kwargs={"key": metric.key})
    if metric.period_field and row.get("weekly", True):
        narrow = {
            "and": [
                {"field": metric.period_field, "op": ">=", "value": start.isoformat()},
                {"field": metric.period_field, "op": "<", "value": (start + timedelta(weeks=1)).isoformat()},
            ]
        }
        url += "?" + urlencode({"narrow": json.dumps(narrow)})
    return {"url": url, "title": f"{row.get('label', '')}, week of {week_short(start)}"}


def week_page(goal_list: "GoalList", request: HttpRequest, start: date) -> dict[str, Any]:
    """One week to read: ``{start, label, iso, state, snapshot, live,
    sections, rows, summary, attention, prev, next, weeks}`` — the snapshot
    if there is one (``live`` False), else worked out now. Each row carries
    ``change`` from the week before (that week's snapshot or live value)."""
    start = week_of(start)
    snaps = weekly_captures(goal_list, [start, start - timedelta(weeks=1)])
    snapshot = snaps.get(start)
    rows = _week_rows(goal_list, request, start, snapshot)
    before = {
        r["id"]: r.get("value")
        for r in _week_rows(goal_list, request, start - timedelta(weeks=1), snaps.get(start - timedelta(weeks=1)))
    }
    # What each goal means is read from the list now, never from a capture: a
    # description is wording, not a measurement, and the newest is the clearest.
    metrics, cards = goal_lookups(goal_list)
    about = {goal["id"]: goal_source(goal, metrics, cards)["description"] for _title, goal in _goal_rows(goal_list)}
    for row in rows:
        row["description"] = about.get(row["id"], "")
        row["change"] = _change(row.get("value"), before.get(row["id"])) if row.get("weekly", True) else None
        row["comparison"] = row["change"]  # the name goals_board.html reads
        row["drill"] = _week_drill(row, start)
    summary = summarize(rows)
    return {
        "start": start,
        "label": week_label(start),
        "iso": iso_week(start),
        "state": week_state(start),
        "heading": "This week so far" if week_state(start) == "current" else "That week",
        "snapshot": snapshot,
        "live": snapshot is None,
        "sections": _sections(rows),
        "rows": rows,
        "summary": summary,
        "attention": [r for r in rows if r["status"] in ("fail", "warn")],
        "prev": start - timedelta(weeks=1),
        "next": start + timedelta(weeks=1) if week_state(start + timedelta(weeks=1)) != "future" else None,
        "has_changes": any(r.get("change") for r in rows),
    }


def week_choices(goal_list: "GoalList", around: date, count: int = 26) -> list[dict[str, Any]]:
    """The weeks a picker offers: the *count* weeks up to this one, newest
    first, each flagged when it has a snapshot."""
    have = {
        timezone.localtime(start).date()
        for start in goal_list.snapshots.filter(cadence="weekly").order_by().values_list("period_start", flat=True)
    }
    newest = this_week()
    weeks = [newest - timedelta(weeks=i) for i in range(count)]
    if around not in weeks:
        weeks.append(around)
    return [
        {"start": w, "label": week_label(w), "snapshot": w in have, "current": w == around, "this_week": w == newest}
        for w in weeks
    ]


def _grid(goal_list: "GoalList", request: HttpRequest, first: date, count: int) -> dict[str, Any]:
    weeks = [first + timedelta(weeks=i) for i in range(count)]
    snaps = weekly_captures(goal_list, weeks)
    live = live_cells(goal_list, request, first, count) if len(snaps) < count else {}
    snap_rows = {w: {r["id"]: r for r in _masked(s.rows, request.user)} for w, s in snaps.items()}
    metrics, cards = goal_lookups(goal_list)
    order: list[tuple[str, str, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for title, goal in _goal_rows(goal_list):
        src = goal_source(goal, metrics, cards)
        order.append(
            (
                goal["id"],
                title,
                src["label"],
                {
                    "target_text": rule_text(goal_at(goal, "weekly", None)["target"], src["fmt"], src["unit"]),
                    "description": src["description"],
                },
            )
        )
        seen.add(goal["id"])
    # Goals that were on the list in a week shown but have since gone.
    for w in weeks:
        for gid, row in snap_rows.get(w, {}).items():
            if gid not in seen:
                order.append(
                    (gid, "No longer on the list", row.get("label", gid), {"target_text": row.get("target_text", "")})
                )
                seen.add(gid)
    rows = []
    for gid, title, label, extra in order:
        cells = []
        for w in weeks:
            if w in snap_rows:
                cell = snap_rows[w].get(gid)
            else:
                cell = live.get(gid, {}).get(w)
            cells.append({"week": w, **cell} if cell else {"week": w, "status": "none", "display": "", "absent": True})
        rows.append({"id": gid, "section": title, "label": label, "cells": cells, **extra})
    columns = []
    for w in weeks:
        shown = [r["cells"][weeks.index(w)] for r in rows]
        scored = [c for c in shown if not c.get("absent") and c.get("status") != "none"]
        columns.append(
            {
                "start": w,
                "short": week_short(w),
                "range": week_range(w),
                "label": week_label(w),
                "iso": iso_week(w),
                "state": week_state(w),
                "snapshot": snaps.get(w),
                "pass": sum(1 for c in scored if c["status"] == "pass"),
                "scored": len(scored),
            }
        )
    return {"weeks": weeks, "columns": columns, "rows": rows}


def week_grid(goal_list: "GoalList", request: HttpRequest, last: date, count: int = GRID_WEEKS) -> dict[str, Any]:
    """Goals down, *count* weeks across ending with *last*: ``{columns:
    [{start, short, label, iso, state, snapshot, pass, scored}], rows: [{id,
    section, label, target_text, cells: [cell]}], sections}``. A week with a
    snapshot shows it; the others are worked out now."""
    last = week_of(last)
    grid = _grid(goal_list, request, last - timedelta(weeks=count - 1), count)
    grid["sections"] = []
    for row in grid["rows"]:
        if not grid["sections"] or grid["sections"][-1]["title"] != row["section"]:
            grid["sections"].append({"title": row["section"], "rows": []})
        grid["sections"][-1]["rows"].append(row)
    grid["last"] = last
    grid["prev"] = last - timedelta(weeks=1)
    grid["next"] = last + timedelta(weeks=1) if week_state(last + timedelta(weeks=1)) != "future" else None
    return grid


def grid_order(raw: Any, grid: dict[str, Any]) -> str:
    """A valid row order for *grid* from ``?order=``, else "" (the list's own
    order, in its sections): ``goal`` / ``-goal`` (by name), or
    ``w<monday>`` / ``-w<monday>`` (by that week's value). Weeks are named by
    date, not position, so an order survives moving between weeks while its
    week is still on screen."""
    order = str(raw or "").strip()
    key = order.lstrip("-")
    if key == "goal":
        return order
    if key.startswith("w") and key[1:] in {c["start"].isoformat() for c in grid["columns"]}:
        return order
    return ""


def _grid_value(row: dict[str, Any], i: int) -> Optional[float]:
    cell = row["cells"][i]
    value = cell.get("value")
    if cell.get("absent") or cell.get("error") or not _is_number(value):
        return None
    return float(value)


def sort_grid(grid: dict[str, Any], order: str) -> dict[str, Any]:
    """*grid* with its rows in *order* (:func:`grid_order`) — one run of rows,
    no section headings (each row keeps its ``section`` to show beside its
    name). Rows with no number in the sorted week go last either way."""
    if not order:
        return {**grid, "order": ""}
    desc, key = order.startswith("-"), order.lstrip("-")
    rows = list(grid["rows"])
    if key == "goal":
        rows.sort(key=lambda r: str(r["label"]).lower(), reverse=desc)
    else:
        i = [c["start"].isoformat() for c in grid["columns"]].index(key[1:])
        have = [r for r in rows if _grid_value(r, i) is not None]
        rest = [r for r in rows if _grid_value(r, i) is None]
        have.sort(key=lambda r: _grid_value(r, i) or 0.0, reverse=desc)
        rows = have + rest
    return {**grid, "rows": rows, "sections": [{"title": "", "rows": rows}], "order": order}


def grid_sort_links(grid: dict[str, Any], order: str) -> dict[str, dict[str, str]]:
    """Per header — ``goal`` and each week's ``w<monday>`` — ``{next,
    aria_sort}``: the ``?order=`` a click asks for. Names start A–Z, weeks
    largest first; a second click flips it (the report table's rule). The
    page offers a way back to the list's own order."""
    out = {}
    for key in ["goal", *[f"w{c['start'].isoformat()}" for c in grid["columns"]]]:
        if order == key:
            out[key] = {"next": f"-{key}", "aria_sort": "ascending"}
        elif order == f"-{key}":
            out[key] = {"next": key, "aria_sort": "descending"}
        else:
            out[key] = {"next": key if key == "goal" else f"-{key}", "aria_sort": "none"}
    return out


def weeks_payload(goal_list: "GoalList", grid: dict[str, Any]) -> dict[str, Any]:
    """A :func:`week_grid`, JSON-safe — what REST and MCP return."""
    return {
        "slug": goal_list.slug,
        "name": goal_list.name,
        "weeks": [
            {
                "start": c["start"].isoformat(),
                "label": c["label"],
                "snapshot": c["snapshot"] is not None,
                "state": c["state"],
                "on_target": c["pass"],
                "scored": c["scored"],
            }
            for c in grid["columns"]
        ],
        "goals": [
            {
                "id": r["id"],
                "section": r["section"],
                "label": r["label"],
                "target_text": r.get("target_text", ""),
                "weeks": [
                    # target_text here is that week's, which a saved week keeps as it was.
                    None
                    if c.get("absent")
                    else {k: c.get(k) for k in ("value", "display", "status", "error", "target_text")}
                    for c in r["cells"]
                ],
            }
            for r in grid["rows"]
        ],
    }


def write_grid_csv(grid: dict[str, Any], out: "SupportsWrite[str]") -> None:
    """The grid as CSV — the spreadsheet, one row per goal: section, goal,
    target, then each period's value and status. Raw values, not formatted."""
    writer = SafeCsvWriter(out)
    head = ["Section", "Goal", "Target"]
    for col in grid["columns"]:
        # A history grid names its own periods: an hour or a month isn't a "week of".
        name = col["label"] if "cadence" in grid else f"Week of {col['start']:%Y-%m-%d}"
        head += [name, f"{name} status"]
    writer.writerow(head)
    for row in grid["rows"]:
        line: list[Any] = [row["section"], row["label"], row.get("target_text", "")]
        for cell in row["cells"]:
            if cell.get("absent"):
                line += ["", ""]
            elif cell.get("restricted"):
                line += ["(restricted)", ""]
            elif cell.get("error"):
                line += [f"(error: {cell['error']})", ""]
            else:
                line += [
                    cell.get("value") if cell.get("value") is not None else "",
                    cell.get("status_label") or STATUS_LABELS[cell.get("status", "none")],
                ]
        writer.writerow(line)


def _better(goal_target: dict[str, Any]) -> Optional[str]:
    op = goal_target.get("op") if isinstance(goal_target, dict) else None
    return "up" if op in (">", ">=") else ("down" if op in ("<", "<=") else None)


def _pct(now: Any, before: Any) -> Optional[float]:
    if not (_is_number(now) and _is_number(before)) or float(before) == 0:
        return None
    return (float(now) - float(before)) / abs(float(before)) * 100


#: What the trends table sorts by: ``?order=`` key → the row's number (or name).
TREND_SORTS = {"goal": "label", "value": "value", "change": "change_pct", "average": "average_pct", "run": "run"}


def trends_order(raw: Any) -> str:
    """A valid order for the trends table from ``?order=``, else "" (the
    list's order): ``goal``, ``value``, ``change``, ``average`` or ``run``,
    ``-`` for descending."""
    order = str(raw or "").strip()
    return order if order.lstrip("-") in TREND_SORTS else ""


def sort_trends(trends: dict[str, Any], order: str) -> dict[str, Any]:
    """*trends* with its rows in *order* (:func:`trends_order`). Names sort
    ignoring case; rows with no number go last either way."""
    if not order:
        return {**trends, "order": ""}
    desc, field = order.startswith("-"), TREND_SORTS[order.lstrip("-")]
    rows = list(trends["rows"])
    if field == "label":
        rows.sort(key=lambda r: str(r["label"]).lower(), reverse=desc)
    else:
        have = [r for r in rows if r.get(field) is not None]
        rest = [r for r in rows if r.get(field) is None]
        have.sort(key=lambda r: r[field], reverse=desc)
        rows = have + rest
    return {**trends, "rows": rows, "order": order}


def trends_sort_links(order: str) -> dict[str, dict[str, str]]:
    """Per sortable header: ``{next, aria_sort}``. The goal name starts A–Z,
    numbers largest first (the longest run, the biggest rise); a second click
    flips it."""
    out = {}
    for key in TREND_SORTS:
        if order == key:
            out[key] = {"next": f"-{key}", "aria_sort": "ascending"}
        elif order == f"-{key}":
            out[key] = {"next": key, "aria_sort": "descending"}
        else:
            out[key] = {"next": key if key == "goal" else f"-{key}", "aria_sort": "none"}
    return out


def week_trends(goal_list: "GoalList", request: HttpRequest, focus: date) -> dict[str, Any]:
    """The weeks around *focus* (:data:`TREND_BEFORE` before, up to
    :data:`TREND_AFTER` after, never past this week), per goal: ``{label,
    points: [{week, short, display, status, height, focus}], value, change
    (vs the week before), vs_average (vs the average of the weeks before),
    streak, best, worst}``, and per week how many goals were on target."""
    focus = week_of(focus)
    first = focus - timedelta(weeks=TREND_BEFORE)
    last = min(focus + timedelta(weeks=TREND_AFTER), this_week())
    count = (last - first).days // 7 + 1
    grid = _grid(goal_list, request, first, count)
    at = grid["weeks"].index(focus)
    goals = {g["id"]: g for _t, g in _goal_rows(goal_list)}
    return {
        "focus": focus,
        "label": week_label(focus),
        "columns": grid["columns"],
        "focus_index": at,
        "rows": [_trend_row(row, at, goals.get(row["id"])) for row in grid["rows"]],
        "before": TREND_BEFORE,
    }


def _trend_row(row: dict[str, Any], at: int, goal: Optional[dict[str, Any]]) -> dict[str, Any]:
    """One grid row read at week *at*: a point per week (bar height against
    the row's largest value), that week's cell, its change against the week
    before and against the average of the weeks before, the run it's on and,
    when the goal says which way is better, its best and worst week so far."""
    cells = row["cells"]
    numbers = [abs(float(c["value"])) for c in cells if _is_number(c.get("value"))]
    top = max(numbers) if numbers else 0
    points = [
        {
            "week": c["week"],
            "short": week_short(c["week"]),
            "label": week_label(c["week"]),
            "display": c.get("display") or "—",
            "status": c.get("status", "none"),
            "status_label": STATUS_LABELS[c.get("status", "none")],
            "height": max(8, round(abs(float(c["value"])) * 100 / top)) if top and _is_number(c.get("value")) else 8,
            "focus": i == at,
            "partial": week_state(c["week"]) == "current",
            "absent": bool(c.get("absent")),
            "change": _change(c.get("value"), cells[i - 1].get("value")) if i > 0 else None,
        }
        for i, c in enumerate(cells)
    ]
    now = cells[at].get("value")
    before = [c.get("value") for c in cells[:at] if _is_number(c.get("value"))]
    average = sum(float(v) for v in before) / len(before) if before else None
    status = cells[at].get("status", "none")
    run = 0
    if status in ("pass", "warn", "fail"):
        for c in reversed(cells[: at + 1]):
            if c.get("status") != status:
                break
            run += 1
    better = _better(goal_at(goal, "weekly", None)["target"]) if goal is not None else None
    valued = [(c["week"], float(c["value"])) for c in cells[: at + 1] if _is_number(c.get("value"))]
    best = worst = None
    if better and len(valued) > 1:
        ranked = sorted(valued, key=lambda wv: wv[1], reverse=better == "up")
        best, worst = week_short(ranked[0][0]), week_short(ranked[-1][0])
    return {
        "id": row["id"],
        "section": row["section"],
        "label": row["label"],
        "target_text": row.get("target_text", ""),
        "points": points,
        "cell": cells[at],
        "change": _change(now, cells[at - 1].get("value")) if at > 0 else None,
        "vs_average": _change(now, average, "the average before") if average is not None else None,
        "average": average,
        "streak": f"{STATUS_LABELS[status]} {run} week{'s' if run != 1 else ''} running" if run >= 2 else "",
        # Numbers the sortable headers order by (None sorts last).
        "value": float(now) if _is_number(now) else None,
        "change_pct": _pct(now, cells[at - 1].get("value")) if at > 0 else None,
        "average_pct": _pct(now, average),
        "run": run,
        "streak_status": status if run >= 2 else "",
        "best": best,
        "worst": worst,
    }


def goal_weeks_trend(
    goal_list: "GoalList", request: HttpRequest, goal_id: str, last: date, count: int = GOAL_TREND_WEEKS
) -> Optional[dict[str, Any]]:
    """The Trends button on a grid row: one goal over *count* weeks ending
    with *last* — its :func:`_trend_row` read at the last week, plus the
    span those weeks cover, which of them were saved, and how many it was on
    target. ``None`` when no goal with that id is on the list or in a saved
    week shown."""
    last = week_of(min(last, this_week()))
    first = last - timedelta(weeks=count - 1)
    grid = _grid(goal_list, request, first, count)
    row = next((r for r in grid["rows"] if r["id"] == goal_id), None)
    if row is None:
        return None
    goal = next((g for _t, g in _goal_rows(goal_list) if g.get("id") == goal_id), None)
    out = _trend_row(row, count - 1, goal)
    saved = {col["start"] for col in grid["columns"] if col["snapshot"]}
    for point in out["points"]:
        point["saved"] = point["week"] in saved
    scored = [c for c in row["cells"] if not c.get("absent") and c.get("status") != "none"]
    out.update(
        {
            "first": first,
            "last": last,
            "focus_short": week_short(last),
            "weeks": count,
            "span": span_label(first, last + timedelta(days=6)),
            "on_target": sum(1 for c in scored if c["status"] == "pass"),
            "scored": len(scored),
        }
    )
    return out
