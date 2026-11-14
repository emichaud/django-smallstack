"""The snapshot engine: a subject's values, captured for a period, kept as they were.

A **period** is an hour, day, week, month or quarter in the site's time zone. A
**capture** (``Snapshot``) is one saving of a subject for one period; a period can
have several, the newest being the one pages show, so nothing is overwritten. A
**tracker** (``SnapshotTracker``) turns on one cadence for one subject, and the
hourly job captures each tracked period once it has ended.

Everything here takes a subject rather than a goal list. A goal list is the only one
registered so far; ``register_subject`` is how another kind of thing joins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model, Q
from django.http import HttpRequest
from django.utils import timezone

from .goals import goal_at, goal_lookups, goal_source, rule_text, summarize
from .metrics import evaluate, may_read, rate_parts, rate_value, request_for
from .weeks import _cell, _goal_rows, _json_safe, _masked, goal_row, week_label, week_short

if TYPE_CHECKING:
    from .models import GoalList, Metric, Snapshot

logger = logging.getLogger(__name__)

HOURLY = "hourly"
DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
QUARTERLY = "quarterly"

#: How many periods the history grid shows, and the most one "fill in" request saves.
GRID_PERIODS = {HOURLY: 24, DAILY: 14, WEEKLY: 8, MONTHLY: 12, QUARTERLY: 8}
MAX_FILL = {HOURLY: 48, DAILY: 60, WEEKLY: 26, MONTHLY: 24, QUARTERLY: 12}
_CADENCE_NOUNS = {HOURLY: "hour", DAILY: "day", WEEKLY: "week", MONTHLY: "month", QUARTERLY: "quarter"}
SUMMARY_KEYS = ("total", "scored", "pass", "warn", "fail", "none", "pct", "headline")
#: Not faults: the number simply doesn't exist at this length. The grid shows them quietly.
NO_HOURLY_VALUE = "This metric only has dates, so it has no value for one hour."
NO_PAST_VALUE = "This number doesn't depend on time, so it can't be worked out for a past period."


# -- periods ------------------------------------------------------------------------


def _midnight(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


@dataclass(frozen=True)
class Period:
    """One hour, day, week, month or quarter: ``start`` included, ``end`` not."""

    cadence: str
    start: datetime
    end: datetime

    @property
    def noun(self) -> str:
        return _CADENCE_NOUNS[self.cadence]

    @property
    def key(self) -> str:
        """The period in a URL or a sort key: naive UTC, so it has no "+" to escape."""
        return self.start.astimezone(dt_timezone.utc).replace(tzinfo=None).isoformat()

    @property
    def state(self) -> str:
        now = timezone.now()
        return "future" if self.start > now else "past" if self.end <= now else "current"

    @property
    def label(self) -> str:
        local = timezone.localtime(self.start)
        if self.cadence == HOURLY:
            return f"{local:%b} {local.day}, {local.year}, {local:%H}:00"
        if self.cadence == DAILY:
            return f"{local:%b} {local.day}, {local.year}"
        if self.cadence == WEEKLY:
            return week_label(local.date())
        if self.cadence == MONTHLY:
            return f"{local:%B %Y}"
        return f"Q{(local.month - 1) // 3 + 1} {local.year}"

    @property
    def short(self) -> str:
        local = timezone.localtime(self.start)
        if self.cadence == HOURLY:
            return f"{local:%H}:00" if local.hour else f"{local:%b} {local.day}"
        if self.cadence == DAILY:
            return f"{local:%b} {local.day}"
        if self.cadence == WEEKLY:
            return week_short(local.date())
        if self.cadence == MONTHLY:
            return f"{local:%b %Y}"
        return f"Q{(local.month - 1) // 3 + 1} {local.year}"

    def shifted(self, steps: int) -> "Period":
        """The period *steps* away. Hours count real time, so a clock change can't
        repeat or lose one; the rest count calendar units."""
        if self.cadence == HOURLY:
            return period_at(HOURLY, self.start.astimezone(dt_timezone.utc) + timedelta(hours=steps))
        local = timezone.localtime(self.start).date()
        if self.cadence == DAILY:
            return period_at(DAILY, _midnight(local + timedelta(days=steps)))
        if self.cadence == WEEKLY:
            return period_at(WEEKLY, _midnight(local + timedelta(weeks=steps)))
        months = 3 * steps if self.cadence == QUARTERLY else steps
        index = local.year * 12 + local.month - 1 + months
        return period_at(self.cadence, _midnight(date(index // 12, index % 12 + 1, 1)))


def period_at(cadence: str, moment: datetime) -> Period:
    """The *cadence* period containing *moment*."""
    if cadence not in _CADENCE_NOUNS:
        raise ValueError(f"unknown cadence {cadence!r} — use one of {', '.join(_CADENCE_NOUNS)}")
    local = timezone.localtime(moment)
    day = local.date()
    if cadence == HOURLY:
        # In UTC: arithmetic on a local time is wall-clock, which goes wrong when the
        # clocks change, and a repeated local hour would compare unequal to itself.
        start = local.replace(minute=0, second=0, microsecond=0).astimezone(dt_timezone.utc)
        return Period(HOURLY, start, start + timedelta(hours=1))
    if cadence == DAILY:
        return Period(DAILY, _midnight(day), _midnight(day + timedelta(days=1)))
    if cadence == WEEKLY:
        monday = day - timedelta(days=day.weekday())
        return Period(WEEKLY, _midnight(monday), _midnight(monday + timedelta(weeks=1)))
    months = 3 if cadence == QUARTERLY else 1
    first = day.month - (day.month - 1) % months
    index = day.year * 12 + first - 1 + months
    return Period(cadence, _midnight(date(day.year, first, 1)), _midnight(date(index // 12, index % 12 + 1, 1)))


def current_period(cadence: str) -> Period:
    return period_at(cadence, timezone.now())


def last_closed(cadence: str) -> Period:
    """The most recent period that has ended."""
    return current_period(cadence).shifted(-1)


def parse_period(cadence: str, raw: Any) -> Optional[Period]:
    """A period from :attr:`Period.key`, or None. Never a future one."""
    try:
        moment = datetime.fromisoformat(str(raw or "")).replace(tzinfo=dt_timezone.utc)
        period = period_at(cadence, moment)
    except ValueError:
        return None
    return None if period.state == "future" else period


# -- a metric's value for a period ----------------------------------------------------


def _span(metric: "Metric", period: Period, hourly: bool) -> dict[str, Any]:
    if hourly:
        lo, hi = period.start.isoformat(), period.end.isoformat()
    else:
        lo = timezone.localtime(period.start).date().isoformat()
        hi = timezone.localtime(period.end).date().isoformat()
    return {
        "and": [
            {"field": metric.period_field, "op": ">=", "value": lo},
            {"field": metric.period_field, "op": "<", "value": hi},
        ]
    }


def window_value(metric: "Metric", request: HttpRequest, period: Period, *, past: bool = False) -> dict[str, Any]:
    """*metric* for one period: ``{value, error, restricted, weekly}`` (``weekly``:
    the number depends on the period at all). With *past*, for a period being filled
    in afterwards, a number that doesn't depend on time has no value rather than
    today's. Asking a date-only column for one hour is an error, not that day's total."""
    from apps.datasets.core import get_dataset

    out: dict[str, Any] = {"value": None, "error": "", "restricted": False, "weekly": bool(metric.period_field)}
    if not may_read(metric, getattr(request, "user", None)):
        out["restricted"] = True
        return out
    if metric.is_rate:
        top, bottom = rate_parts(metric)
        if top is None or bottom is None or bool(top.period_field) != bool(bottom.period_field):
            out["error"] = "This rate's two metrics can't be compared."
            return out
        above = window_value(top, request, period, past=past)
        below = window_value(bottom, request, period, past=past)
        out["restricted"] = above["restricted"] or below["restricted"]
        out["error"] = above["error"] or below["error"]
        if not out["restricted"] and not out["error"]:
            out["value"] = rate_value(above["value"], below["value"], metric.format)
        return out
    if not metric.period_field:
        if past:
            out["error"] = NO_PAST_VALUE
            return out
        result = evaluate(metric, request)
    else:
        hourly = period.cadence == HOURLY
        ds = get_dataset(metric.dataset)
        if hourly and ds is not None and ds.filter_column_types().get(metric.period_field) == "date":
            out["error"] = NO_HOURLY_VALUE
            return out
        result = evaluate(metric, request, extra_tree=_span(metric, period, hourly))
    out["restricted"] = result.restricted
    out["error"] = result.error or ""
    out["value"] = result.value if result.ok else None
    return out


# -- subjects ---------------------------------------------------------------------------


def goal_list_rows(goal_list: "GoalList", request: HttpRequest, period: Period, *, past: bool = False) -> list[Any]:
    """Every goal for *period*, in what a capture stores (``weeks.goal_row``)."""
    metrics, cards = goal_lookups(goal_list)
    seen: dict[str, dict[str, Any]] = {}
    rows = []
    for title, stored in _goal_rows(goal_list):
        src = goal_source(stored, metrics, cards)
        metric = src["metric"]
        goal = goal_at(stored, period.cadence, metric)
        if metric is None:
            cell = _cell(goal, None, src, error="Its metric or card no longer exists.")
        else:
            if metric.key not in seen:
                seen[metric.key] = window_value(metric, request, period, past=past)
            got = seen[metric.key]
            cell = {
                **_cell(goal, got["value"], src, error=got["error"], restricted=got["restricted"]),
                "weekly": got["weekly"],
            }
        rows.append(goal_row(title, goal, src, cell))
    return rows


@dataclass(frozen=True)
class Subject:
    """How the engine captures one kind of thing."""

    rows: Callable[..., list[Any]]
    user: Callable[[Any], Any]
    ready: Callable[[Any], bool]


_SUBJECTS: dict[type[Model], Subject] = {}


def register_subject(
    model: type[Model],
    *,
    rows: Callable[..., list[Any]],
    user: Callable[[Any], Any],
    ready: Callable[[Any], bool] = lambda obj: True,
) -> None:
    """Let *model* be captured: ``rows(obj, request, period, past=)`` gives what a
    capture stores (each with ``status``, for the summary), ``user(obj)`` whose
    access to capture with, ``ready(obj)`` whether there's anything to capture."""
    _SUBJECTS[model] = Subject(rows, user, ready)


def _subject(obj: Any) -> Subject:
    try:
        return _SUBJECTS[type(obj)]
    except KeyError:
        raise ValueError(f"{type(obj).__name__} can't be captured: it isn't a registered subject") from None


# -- capturing ----------------------------------------------------------------------------


def _for_subject(model: Any, obj: Any) -> Any:
    return model.objects.filter(subject_type=ContentType.objects.get_for_model(obj), subject_id=obj.pk)


def capture(obj: Any, period: Period, *, by: Any = None, reason: str = "", past: bool = False) -> "Snapshot":
    """Save *obj* for *period* as a new capture. Earlier ones stay. Refuses a period
    that hasn't started."""
    from .models import Snapshot

    if period.state == "future":
        raise ValueError(f"That {period.noun} hasn't started yet.")
    subject = _subject(obj)
    rows = _json_safe(subject.rows(obj, request_for(subject.user(obj)), period, past=past))
    summary = summarize(rows)
    return Snapshot.objects.create(
        subject=obj,
        cadence=period.cadence,
        period_start=period.start,
        period_end=period.end,
        rows=rows,
        summary={k: summary[k] for k in SUMMARY_KEYS},
        complete=period.state == "past",
        taken_by=by,
        reason=reason,
    )


def latest_captures(obj: Any, cadence: str, periods: Iterable[Period]) -> dict[datetime, "Snapshot"]:
    """``{period start: its newest capture}``, for the periods that have one."""
    from .models import Snapshot

    starts = [p.start for p in periods]
    out: dict[datetime, Snapshot] = {}
    # Oldest first, so the newest overwrites.
    captures = _for_subject(Snapshot, obj).filter(cadence=cadence, period_start__in=starts)
    for snapshot in captures.order_by("taken_at", "pk"):
        out[snapshot.period_start] = snapshot
    return out


def captures_of(obj: Any, period: Period) -> list["Snapshot"]:
    """Every capture of *period*, newest first."""
    from .models import Snapshot

    found = _for_subject(Snapshot, obj).filter(cadence=period.cadence, period_start=period.start)
    return list(found.select_related("taken_by").order_by("-taken_at", "-pk"))


def fill(obj: Any, cadence: str, count: int, *, by: Any = None, replace_existing: bool = False) -> int:
    """Capture the past *count* periods with no finished capture yet (all of them
    with *replace_existing*), against today's targets. One saved part-way through
    doesn't count: it isn't that period's number. Returns how many."""
    periods = [last_closed(cadence).shifted(-i) for i in range(max(1, min(int(count), MAX_FILL[cadence])))]
    have = latest_captures(obj, cadence, periods)
    done = 0
    for period in periods:
        if replace_existing or period.start not in have or not have[period.start].complete:
            capture(obj, period, by=by, past=True, reason="Filled in afterwards")
            done += 1
    return done


def recapture_for_value(metric: "Metric", day: date, *, by: Any = None) -> int:
    """A hand-entered value for *day* changed: add a capture to each period holding
    that day whose rows use the metric or a rate on it. The Monday job usually runs
    before anyone has typed last week's numbers, so the meeting would otherwise show
    a blank. The earlier capture stays, and the new one keeps its targets. Hourly
    captures are left alone: a value entered for a date has no hour. Returns how
    many captures were added."""
    from .models import Metric, Snapshot

    affected = {
        metric.key,
        *Metric.objects.filter(source="rate")
        .filter(Q(numerator=metric.key) | Q(denominator=metric.key))
        .values_list("key", flat=True),
    }
    candidates = Snapshot.objects.filter(
        period_start__lt=_midnight(day + timedelta(days=1)), period_end__gt=_midnight(day)
    ).exclude(cadence=HOURLY)
    newest: dict[tuple[Any, ...], Snapshot] = {}
    for snapshot in candidates.order_by("taken_at", "pk"):
        newest[(snapshot.subject_type_id, snapshot.subject_id, snapshot.cadence, snapshot.period_start)] = snapshot
    added = 0
    for snapshot in newest.values():
        hit = [r for r in snapshot.rows if r.get("metric_key") in affected]
        subject = snapshot.subject
        if not hit or subject is None:
            continue
        request = request_for(_subject(subject).user(subject))
        period = Period(snapshot.cadence, snapshot.period_start, snapshot.period_end)
        metrics, cards = goal_lookups(subject)
        rows = [dict(r) for r in snapshot.rows]
        for row in rows:
            if row.get("metric_key") not in affected:
                continue
            source = Metric.objects.filter(key=row["metric_key"]).first()
            if source is None:
                continue
            goal = {k: row.get(k) for k in ("target", "warn", "metric", "component")}
            got = window_value(source, request, period)
            cell = _cell(
                goal, got["value"], goal_source(goal, metrics, cards), error=got["error"], restricted=got["restricted"]
            )
            row.update({k: cell[k] for k in ("value", "display", "unit", "status", "gap_text", "error")})
        rows = _json_safe(rows)
        summary = summarize(rows)
        Snapshot.objects.create(
            subject=subject,
            cadence=snapshot.cadence,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            rows=rows,
            summary={k: summary[k] for k in SUMMARY_KEYS},
            complete=snapshot.complete,
            taken_by=by,
            reason="A value changed",
        )
        added += 1
    return added


# -- tracking -----------------------------------------------------------------------------


def tracked_cadences(obj: Any) -> list[str]:
    from .models import SnapshotTracker

    have = set(_for_subject(SnapshotTracker, obj).values_list("cadence", flat=True))
    return [c for c in _CADENCE_NOUNS if c in have]


def set_tracking(obj: Any, cadences: Iterable[str], *, by: Any = None) -> list[str]:
    """Track exactly *cadences* for *obj*. Turning one off keeps what it captured."""
    from .models import SnapshotTracker

    wanted = set(cadences)
    unknown = sorted(wanted - set(_CADENCE_NOUNS))
    if unknown:
        raise ValueError(f"unknown cadence {unknown[0]!r} — use one of {', '.join(_CADENCE_NOUNS)}")
    _for_subject(SnapshotTracker, obj).exclude(cadence__in=wanted).delete()
    have = set(tracked_cadences(obj))
    for cadence in wanted - have:
        SnapshotTracker.objects.create(subject=obj, cadence=cadence, created_by=by)
    return tracked_cadences(obj)


def default_cadences() -> list[str]:
    """What a new subject tracks until someone changes it."""
    return list(getattr(settings, "SMALLSTACK_SNAPSHOT_DEFAULT_CADENCES", [WEEKLY]))


def capture_due() -> int:
    """The hourly job: for each tracker, capture the latest ended period if it has no
    finished capture yet. One saved by hand part-way through doesn't count, or Tuesday's
    numbers would stand for the whole week. Safe to run any number of times. One
    subject's failure doesn't stop the rest. Returns how many captures it took."""
    from .models import Snapshot, SnapshotTracker

    done = 0
    for tracker in SnapshotTracker.objects.select_related("subject_type"):
        subject = tracker.subject
        if subject is None:
            continue
        period = last_closed(tracker.cadence)
        try:
            handler = _subject(subject)
            if handler.user(subject) is None or not handler.ready(subject):
                continue
            finished = _for_subject(Snapshot, subject).filter(
                cadence=tracker.cadence, period_start=period.start, complete=True
            )
            if finished.exists():
                continue
            capture(subject, period)
            done += 1
        except Exception:  # noqa: BLE001 — one subject's failure must not stop the rest
            logger.exception("snapshots: capturing %s for %s failed", subject, period.label)
    return done


def prune() -> int:
    """Delete captures older than ``SMALLSTACK_SNAPSHOT_KEEP_DAYS`` for their cadence.
    A cadence that isn't listed is kept for good. Returns how many went."""
    from .models import Snapshot

    keep = getattr(settings, "SMALLSTACK_SNAPSHOT_KEEP_DAYS", {HOURLY: 90, DAILY: 730})
    removed = 0
    for cadence, days in keep.items():
        cutoff = timezone.now() - timedelta(days=int(days))
        removed += Snapshot.objects.filter(cadence=cadence, period_end__lt=cutoff).delete()[0]
    return removed


# -- reading -------------------------------------------------------------------------------


def history_grid(obj: Any, request: HttpRequest, cadence: str, last: Optional[Period] = None) -> dict[str, Any]:
    """Goals down, periods across with the newest first (24 hours don't fit on a
    screen, and the latest is what you came for), from captures only: a period with
    none is blank, never worked out now. The shape ``weeks.sort_grid`` and
    ``write_grid_csv`` read."""
    newest = last or current_period(cadence)
    count = GRID_PERIODS[cadence]
    periods = [newest.shifted(-i) for i in range(count)]
    found = latest_captures(obj, cadence, periods)
    masked = {start: {r["id"]: r for r in _masked(s.rows, request.user)} for start, s in found.items()}
    metrics, cards = goal_lookups(obj)
    order: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for title, goal in _goal_rows(obj):
        src = goal_source(goal, metrics, cards)
        rule = goal_at(goal, cadence, src["metric"])["target"]
        order.append((goal["id"], title, src["label"], rule_text(rule, src["fmt"], src["unit"])))
        seen.add(goal["id"])
    for rows_by_id in masked.values():
        for gid, row in rows_by_id.items():
            if gid not in seen:
                order.append((gid, "No longer on the list", row.get("label", gid), row.get("target_text", "")))
                seen.add(gid)
    rows: list[dict[str, Any]] = []
    for gid, title, label, target_text in order:
        cells: list[dict[str, Any]] = []
        for period in periods:
            cell = masked.get(period.start, {}).get(gid)
            if cell and cell.get("error") in (NO_HOURLY_VALUE, NO_PAST_VALUE):
                cell = {**cell, "not_applicable": True}
            cells.append(cell if cell else {"status": "none", "display": "", "absent": True})
        rows.append({"id": gid, "section": title, "label": label, "target_text": target_text, "cells": cells})
    columns = []
    for i, period in enumerate(periods):
        scored = [r["cells"][i] for r in rows if not r["cells"][i].get("absent") and r["cells"][i]["status"] != "none"]
        columns.append(
            {
                # Naive UTC: weeks.grid_order and friends call .isoformat() on this for a sort key.
                "start": datetime.fromisoformat(period.key),
                "key": period.key,
                "short": period.short,
                "label": period.label,
                "state": period.state,
                "snapshot": found.get(period.start),
                "pass": sum(1 for c in scored if c["status"] == "pass"),
                "scored": len(scored),
            }
        )
    sections: list[dict[str, Any]] = []
    for row in rows:
        if not sections or sections[-1]["title"] != row["section"]:
            sections.append({"title": row["section"], "rows": []})
        sections[-1]["rows"].append(row)
    following = newest.shifted(count)
    return {
        "has_not_applicable": any(c.get("not_applicable") for r in rows for c in r["cells"]),
        "cadence": cadence,
        "periods": periods,
        "columns": columns,
        "rows": rows,
        "sections": sections,
        "prev": newest.shifted(-count),
        "next": following
        if following.state != "future"
        else (None if newest.state == "current" else current_period(cadence)),
    }


def history_payload(obj: Any, grid: dict[str, Any]) -> dict[str, Any]:
    """A :func:`history_grid`, JSON-safe, for REST and MCP."""

    def safe(value: Any) -> Any:
        return float(value) if isinstance(value, Decimal) else value

    return {
        "slug": getattr(obj, "slug", ""),
        "name": getattr(obj, "name", str(obj)),
        "cadence": grid["cadence"],
        "tracked": tracked_cadences(obj),
        "periods": [
            {
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
                "label": column["label"],
                "state": column["state"],
                "captured": column["snapshot"] is not None,
                "taken_at": column["snapshot"].taken_at.isoformat() if column["snapshot"] else None,
                "on_target": column["pass"],
                "scored": column["scored"],
            }
            for period, column in zip(grid["periods"], grid["columns"], strict=True)
        ],
        "goals": [
            {
                "id": r["id"],
                "section": r["section"],
                "label": r["label"],
                "periods": [
                    None
                    if c.get("absent")
                    else {
                        **{k: c.get(k) for k in ("display", "status", "error", "target_text")},
                        "value": safe(c.get("value")),
                    }
                    for c in r["cells"]
                ],
            }
            for r in grid["rows"]
        ],
    }


__all__ = [
    "DAILY",
    "GRID_PERIODS",
    "HOURLY",
    "MAX_FILL",
    "MONTHLY",
    "Period",
    "QUARTERLY",
    "WEEKLY",
    "capture",
    "capture_due",
    "captures_of",
    "current_period",
    "fill",
    "history_grid",
    "history_payload",
    "last_closed",
    "latest_captures",
    "parse_period",
    "period_at",
    "prune",
    "recapture_for_value",
    "register_subject",
    "set_tracking",
    "tracked_cadences",
    "window_value",
]
