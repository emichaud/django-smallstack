"""MCP tools for building dashboards and KPIs agentically.

The CRUD (``create_metric`` / ``update_dashboard`` / ``list_reports`` …) is
generated from the CRUDViews. These add what CRUD can't:

- ``list_dashboard_components`` — the card types, their options, the periods
- ``metric_preview``   — dry-run an unsaved metric: value + row count + every problem
- ``metric_value``     — evaluate a saved metric (optionally for a period)
- ``metric_trend``     — a saved metric per day / week / month across a period (what a chart reads)
- ``dashboard_snapshot`` — every card on a dashboard, evaluated (check your work)
- ``dashboard_add_card`` / ``dashboard_remove_card`` — edit one card, not the whole layout (or place a saved one)
- ``card_preview``     — render an unsaved card (the component builder's dry run)
- ``dashboard_set_picture`` — the dashboard's picture, sent as base64 (or removed)
- ``report_values``    — a report's matrix
- ``playlist_slides``  — a playlist as the caller sees it (the CRUD tools create and edit one)
- ``goal_list_values`` — a goal list judged: each goal's value, status (on target / at risk / missed), target
- ``goal_list_add_goal`` — append one goal to a section of a goal list
- ``goal_list_weeks``  — a goal list week over week (saved snapshots, or worked out)

The intended loop: ``list_datasets`` → ``describe_dataset`` → ``metric_preview``
(until ``problems`` is empty and the number is plausible) → ``create_metric`` →
``create_dashboard`` → ``dashboard_add_card`` × N → ``dashboard_snapshot``.

Every tool reads as the token's user: ownership (``can_view`` / ``can_edit``)
and each dataset's ``access`` tier apply exactly as on the pages.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("smallstack.dashboards")


def _user() -> Any:
    from apps.mcp.server import current_context

    return getattr(current_context(), "user", None)


def _components(args: dict[str, Any]) -> dict[str, Any]:
    from .components import components_payload

    return components_payload(_user())


def _preview(args: dict[str, Any]) -> dict[str, Any]:
    from .previews import preview_metric

    return preview_metric(_user(), args)


def _metric_value(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import evaluate, request_for
    from .models import Metric

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    from .comparison import compare_with_previous

    period = str(args.get("period") or "") or None
    req = request_for(user)
    result = evaluate(metric, req, period=period)
    return {
        "key": metric.key,
        "name": metric.name,
        "url": metric.get_absolute_url(),
        **result.as_dict(),
        # The pages' comparison: this period against the one before it (null
        # for all time or a rolling window — they have no defined predecessor).
        "comparison": compare_with_previous(metric, req, period, result),
    }


def _metric_trend(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .models import Metric
    from .trends import metric_trend

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    period = str(args.get("period") or "") or None
    grain = str(args.get("grain") or "") or None
    trend = metric_trend(metric, request_for(user), period, grain)
    return {"key": metric.key, "name": metric.name, **trend}


def _dashboard(user: Any, slug: Any) -> Any:
    from .models import Dashboard

    dashboard = Dashboard.objects.filter(slug=str(slug or "")).first()
    if dashboard is None or not dashboard.can_view(user):
        return None
    return dashboard


def _snapshot(args: dict[str, Any]) -> dict[str, Any]:
    from apps.datasets.dateranges import is_period

    from .boards import board_values
    from .metrics import request_for

    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    raw = args.get("period")
    period = dashboard.default_period or None if raw is None else (raw if is_period(raw) else None)
    return {
        "slug": dashboard.slug,
        "name": dashboard.name,
        "url": dashboard.get_absolute_url(),
        "period": period,
        "cells": board_values(dashboard, request_for(user), period),
    }


def _add_card(args: dict[str, Any]) -> dict[str, Any]:
    from django.core.exceptions import ValidationError

    from .components import get_component_type, next_position

    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    if not dashboard.can_edit(user):
        return {"error": "you may not edit this dashboard"}
    component = None
    if args.get("component"):
        from .models import Component

        component = Component.objects.filter(key=str(args["component"])).first()
        if component is None or not component.can_view(user):
            return {"error": f"no saved card {args.get('component')!r} — use list_components"}
    ct = get_component_type(component.type if component else str(args.get("type") or ""))
    if ct is None:
        return {"error": f"unknown type {args.get('type')!r} — use list_dashboard_components"}
    w = int(args.get("w") or ct.default_size[0])
    h = int(args.get("h") or ct.default_size[1])
    x, y = next_position(dashboard.layout, w)
    cell: dict[str, Any] = {
        "x": args["x"] if args.get("x") is not None else x,
        "y": args["y"] if args.get("y") is not None else y,
        "w": w,
        "h": h,
    }
    if component is not None:
        cell["component"] = component.key  # its type, metric and options come from the saved card
        placed_keys: tuple[str, ...] = ("title", "id")
    else:
        cell["type"] = ct.key
        placed_keys = ("metric", "title", "options", "id")
    for key in placed_keys:
        if args.get(key) not in (None, ""):
            cell[key] = args[key]
    if args.get("use_period") is False:
        cell["use_period"] = False
    before = {c.get("id") for c in dashboard.layout}
    dashboard.layout = [*dashboard.layout, cell]
    try:
        dashboard.save()
    except ValidationError as exc:
        return {"error": "the card was not added", "problems": exc.message_dict.get("layout", exc.messages)}
    added = next(c for c in dashboard.layout if c.get("id") not in before)
    return {"ok": True, "cell": added, "url": dashboard.get_absolute_url(), "cells": len(dashboard.layout)}


def _remove_card(args: dict[str, Any]) -> dict[str, Any]:
    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    if not dashboard.can_edit(user):
        return {"error": "you may not edit this dashboard"}
    cell_id = str(args.get("cell_id") or "")
    if dashboard.cell(cell_id) is None:
        return {"error": f"no cell {cell_id!r} on this dashboard"}
    dashboard.layout = [c for c in dashboard.layout if c.get("id") != cell_id]
    dashboard.save()
    return {"ok": True, "cells": len(dashboard.layout)}


def _set_picture(args: dict[str, Any]) -> dict[str, Any]:
    import base64
    import binascii

    from django.core.files.uploadedfile import SimpleUploadedFile

    from .boards import clear_picture, set_picture
    from .models import MAX_COVER_BYTES

    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    if not dashboard.can_edit(user):
        return {"error": "you may not edit this dashboard"}
    if args.get("remove"):
        return clear_picture(dashboard)
    encoded = str(args.get("image_base64") or "")
    if not encoded:
        return {"error": "send image_base64 (or remove: true)"}
    if len(encoded) > (MAX_COVER_BYTES * 4) // 3 + 4:
        return {"error": f"the picture is over the {MAX_COVER_BYTES // (1024 * 1024)}MB limit"}
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return {"error": "image_base64 is not valid base64"}
    name = str(args.get("filename") or "picture.png")
    return set_picture(dashboard, SimpleUploadedFile(name, raw), str(args.get("alt") or ""))


def _playlist_slides(args: dict[str, Any]) -> dict[str, Any]:
    from .models import Playlist
    from .playlists import playlist_payload

    user = _user()
    playlist = Playlist.objects.filter(slug=str(args.get("playlist") or "")).first()
    if playlist is None or not playlist.can_view(user):
        return {"error": f"no playlist {args.get('playlist')!r} — use list_playlists"}
    return playlist_payload(playlist, user)


def _goal_list_values(args: dict[str, Any]) -> dict[str, Any]:
    from .goals import goal_values
    from .metrics import request_for
    from .models import GoalList

    user = _user()
    goal_list = GoalList.objects.filter(slug=str(args.get("goal_list") or "")).first()
    if goal_list is None or not goal_list.can_view(user):
        return {"error": f"no goal list {args.get('goal_list')!r} — use list_goal_lists"}
    period = args.get("period")
    if period not in (None, ""):
        from apps.datasets.dateranges import is_period

        if period != "all" and not is_period(str(period)):
            return {"error": f"unknown period {period!r} — list_dashboard_components lists them"}
    return goal_values(
        goal_list, request_for(user), period=None if period in (None, "") else ("" if period == "all" else str(period))
    )


def _goal_list_weeks(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .models import GoalList
    from .weeks import GRID_WEEKS, parse_week, this_week, week_grid, weeks_payload

    user = _user()
    goal_list = GoalList.objects.filter(slug=str(args.get("goal_list") or "")).first()
    if goal_list is None or not goal_list.can_view(user):
        return {"error": f"no goal list {args.get('goal_list')!r} — use list_goal_lists"}
    last = parse_week(args.get("week")) or this_week()
    count = max(1, min(int(args.get("weeks") or GRID_WEEKS), 26))
    return weeks_payload(goal_list, week_grid(goal_list, request_for(user), min(last, this_week()), count))


def _goal_list_add_goal(args: dict[str, Any]) -> dict[str, Any]:
    from django.core.exceptions import ValidationError

    from .goals import add_goal
    from .models import GoalList

    user = _user()
    goal_list = GoalList.objects.filter(slug=str(args.get("goal_list") or "")).first()
    if goal_list is None or not goal_list.can_view(user):
        return {"error": f"no goal list {args.get('goal_list')!r} — use list_goal_lists"}
    if not goal_list.can_edit(user):
        return {"error": "you can view this goal list but not edit it"}
    keys = ("metric", "component", "label", "target", "warn", "period", "note")
    goal: dict[str, Any] = {k: args[k] for k in keys if k in args}
    try:
        stored = add_goal(goal_list, goal, str(args.get("section") or ""))
    except ValidationError as exc:
        return {"error": "the goal doesn't fit", "problems": exc.message_dict.get("sections", exc.messages)}
    return {"ok": True, "goal": stored, "url": goal_list.get_absolute_url()}


def _card_preview(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .previews import preview_card

    user = _user()
    return preview_card(user, args, request_for(user))


def _report_values(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .models import Report
    from .reports import report_values

    user = _user()
    report = Report.objects.filter(slug=str(args.get("report") or "")).first()
    if report is None or not report.can_view(user):
        return {"error": f"no report {args.get('report')!r} — use list_reports"}
    out = report_values(report, request_for(user))
    out["url"] = report.get_absolute_url()
    return out


_FILTER_TREE_DOC = (
    'Nested AND/OR filter: {"and": [{"field": "status", "op": "=", "value": "open"}, {"or": [...]}, '
    '{"field": "created_at", "op": "period", "value": "mtd"}]}. Ops: = != > >= < <= between(value,value2) '
    "in(list) contains isnull period. describe_dataset lists each field's ops and the period keys."
)


def register_dashboard_tools() -> int:
    try:
        from apps.mcp.server import tool
    except Exception:
        logger.info("apps.mcp not available — skipping dashboard MCP tools")
        return 0

    obj = "object"
    specs: list[tuple[str, str, dict[str, Any], Any, bool]] = [
        (
            "list_dashboard_components",
            "The card types a dashboard cell can be (with their options and default sizes), the period "
            "keys a dashboard/report/metric can use, and (for staff) the dashboard widgets. Read before "
            "writing a dashboard layout.",
            {"type": obj, "properties": {}, "additionalProperties": False},
            _components,
            False,
        ),
        (
            "metric_preview",
            "Dry-run a metric WITHOUT saving it: returns its value, display, threshold state, the number of "
            "matching rows, a one-line reading of the filter, and every validation problem (unknown field, bad "
            "op, missing measure…). Iterate until problems is empty, then create_metric with the same fields.",
            {
                "type": obj,
                "properties": {
                    "dataset": {"type": "string", "description": "Dataset key (list_datasets)."},
                    "filter_tree": {"type": "object", "description": _FILTER_TREE_DOC},
                    "agg": {"type": "string", "enum": ["count", "distinct", "sum", "avg", "min", "max"]},
                    "measure": {"type": "string", "description": "Column to aggregate (not for count)."},
                    "period_field": {"type": "string", "description": "Date column a period narrows."},
                    "period": {"type": "string", "description": "Evaluate for this period (mtd, last_30, …)."},
                    "format": {
                        "type": "string",
                        "enum": ["number", "compact", "decimal", "percent", "currency", "duration"],
                    },
                    "unit": {"type": "string"},
                    "thresholds": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": 'State rules, first match wins: [{"op": ">=", "value": 10, "state": "danger"}]. '
                        "States: success, warning, danger, muted.",
                    },
                },
                "required": ["dataset"],
                "additionalProperties": False,
            },
            _preview,
            False,
        ),
        (
            "metric_value",
            "Evaluate a saved metric — value, display, state, the filter's reading. Optional period; for "
            "today / wtd / mtd / qtd / ytd it also returns `comparison` against the previous period "
            "({dir: up|down|flat, text, previous}), the same line the pages show.",
            {
                "type": obj,
                "properties": {"key": {"type": "string"}, "period": {"type": "string"}},
                "required": ["key"],
                "additionalProperties": False,
            },
            _metric_value,
            False,
        ),
        (
            "metric_trend",
            "A saved metric over time: its value per day / week / month / quarter / year across a period "
            "(default grain fits the span; no period = the last 12 buckets with data). Every bucket is "
            "present — empty ones read 0 for count/sum, null for averages — and the running one has "
            "partial: true. Needs a metric with a period_field.",
            {
                "type": obj,
                "properties": {
                    "key": {"type": "string"},
                    "period": {"type": "string", "description": "A period key, e.g. last_30, mtd, ytd."},
                    "grain": {"type": "string", "enum": ["day", "week", "month", "quarter", "year"]},
                },
                "required": ["key"],
                "additionalProperties": False,
            },
            _metric_trend,
            False,
        ),
        (
            "dashboard_snapshot",
            "Every card on a dashboard, evaluated — use it to check a dashboard you built. Optional period "
            "(default: the dashboard's own).",
            {
                "type": obj,
                "properties": {
                    "dashboard": {"type": "string", "description": "Dashboard slug."},
                    "period": {"type": "string"},
                },
                "required": ["dashboard"],
                "additionalProperties": False,
            },
            _snapshot,
            False,
        ),
        (
            "dashboard_add_card",
            "Append one card to a dashboard (placed below the existing cards unless x/y are given). Either "
            "component = a saved card's key (list_components; its design stays in step when the card is edited), "
            "or an inline card: type from list_dashboard_components; metric = a metric key for metric/metric_group; "
            'options per type (metric_group: {"dimension": "<column>", "limit": 5}; text: {"markdown": "..."}; '
            'widget: {"widget": "<key>"}).',
            {
                "type": obj,
                "properties": {
                    "dashboard": {"type": "string", "description": "Dashboard slug."},
                    "component": {
                        "type": "string",
                        "description": "A saved card's key, instead of type/metric/options.",
                    },
                    "type": {"type": "string"},
                    "metric": {"type": "string"},
                    "title": {"type": "string"},
                    "options": {"type": "object"},
                    "w": {"type": "integer", "minimum": 1, "maximum": 12},
                    "h": {"type": "integer", "minimum": 1, "maximum": 12},
                    "x": {"type": "integer", "minimum": 0, "maximum": 11},
                    "y": {"type": "integer", "minimum": 0},
                    "use_period": {"type": "boolean", "description": "false = ignore the dashboard period."},
                },
                "required": ["dashboard"],
                "additionalProperties": False,
            },
            _add_card,
            True,
        ),
        (
            "dashboard_remove_card",
            "Remove one card from a dashboard by its cell id (dashboard_snapshot lists them).",
            {
                "type": obj,
                "properties": {"dashboard": {"type": "string"}, "cell_id": {"type": "string"}},
                "required": ["dashboard", "cell_id"],
                "additionalProperties": False,
            },
            _remove_card,
            True,
        ),
        (
            "dashboard_set_picture",
            "Set the picture that represents a dashboard in lists and beside its title: a PNG, JPEG, GIF or "
            "WebP up to 5MB, base64-encoded. filename's extension names the format. alt describes it for "
            "screen readers (blank = decoration). remove: true clears the picture instead.",
            {
                "type": obj,
                "properties": {
                    "dashboard": {"type": "string", "description": "Dashboard slug."},
                    "image_base64": {"type": "string"},
                    "filename": {"type": "string", "description": "e.g. team.png"},
                    "alt": {"type": "string"},
                    "remove": {"type": "boolean"},
                },
                "required": ["dashboard"],
                "additionalProperties": False,
            },
            _set_picture,
            True,
        ),
        (
            "card_preview",
            "Render an UNSAVED card (dry run): {type, metric?, options?, name?, period?, visibility?} → "
            "{html, problems}. Validated exactly as a dashboard cell; iterate until problems is empty, then "
            "create_component with the same fields to save it.",
            {
                "type": obj,
                "properties": {
                    "type": {"type": "string"},
                    "metric": {"type": "string"},
                    "options": {"type": "object"},
                    "name": {"type": "string"},
                    "period": {"type": "string"},
                    "visibility": {"type": "string", "enum": ["personal", "shared"]},
                },
                "required": ["type"],
                "additionalProperties": False,
            },
            _card_preview,
            False,
        ),
        (
            "playlist_slides",
            "A dashboard playlist as you'd see it: each slide's dashboard, seconds and period, and the "
            "player url (add ?slide=N&play=1&seconds=N&loop=0&kiosk=1 to control it). Dashboards you "
            "can't open are left out.",
            {
                "type": obj,
                "properties": {"playlist": {"type": "string", "description": "Playlist slug."}},
                "required": ["playlist"],
                "additionalProperties": False,
            },
            _playlist_slides,
            False,
        ),
        (
            "goal_list_values",
            "Judge a goal list: per section, each goal's value, status (pass = on target, warn = at risk, "
            "fail = missed, none = no number), its target and at-risk rules in words, how far a miss is "
            'from target, and the change from the previous period; plus a summary ("7 of 9 on target").',
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string", "description": "Goal list slug."},
                    "period": {
                        "type": "string",
                        "description": "Judge over this period instead of the list's own ('all' = all time).",
                    },
                },
                "required": ["goal_list"],
                "additionalProperties": False,
            },
            _goal_list_values,
            False,
        ),
        (
            "goal_list_weeks",
            "A goal list week over week (weeks run Monday to Sunday): per goal, each week's value and status "
            "against its target. Saved weeks (snapshot: true) are the values and targets as they were; the "
            "rest are worked out now. Ends with `week` (any day of it, default this week).",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string", "description": "Goal list slug."},
                    "week": {"type": "string", "description": "The last week shown: a date (YYYY-MM-DD) or 2026-W45."},
                    "weeks": {"type": "integer", "description": "How many weeks (1-26, default 8)."},
                },
                "required": ["goal_list"],
                "additionalProperties": False,
            },
            _goal_list_weeks,
            False,
        ),
        (
            "goal_list_add_goal",
            "Append one goal to a goal list: a metric (or a single-stat card) and its target rule. The goal "
            "goes at the end of the section titled `section` (matched ignoring case), which is started at the "
            "end of the list if it doesn't exist. Check the result with goal_list_values.",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string", "description": "Goal list slug."},
                    "section": {"type": "string", "description": "Section title; blank = an untitled section."},
                    "metric": {"type": "string", "description": "Metric key (or give component)."},
                    "component": {"type": "string", "description": "A single-stat saved card's key."},
                    "label": {"type": "string", "description": "Shown instead of the metric's name."},
                    "target": {
                        "type": obj,
                        "description": 'On target when the value meets this: {"op": ">=", "value": 95}; '
                        'ops > >= < <= = != between ({"op": "between", "value": [lo, hi]}).',
                    },
                    "warn": {"type": obj, "description": "The at-risk line, same shape; optional."},
                    "period": {"type": "string", "description": "A period key or 'all'; blank = the list's."},
                    "note": {"type": "string", "description": "A short note shown under the goal (owner, context)."},
                },
                "required": ["goal_list", "target"],
                "additionalProperties": False,
            },
            _goal_list_add_goal,
            True,
        ),
        (
            "report_values",
            "Evaluate a KPI report: one row per metric, one column per period.",
            {
                "type": obj,
                "properties": {"report": {"type": "string", "description": "Report slug."}},
                "required": ["report"],
                "additionalProperties": False,
            },
            _report_values,
            False,
        ),
    ]
    count = 0
    for name, description, schema, handler, write in specs:
        try:
            tool(name, description, schema, write=write, requires_access=None if write else "readonly")(handler)
            count += 1
        except Exception:
            logger.exception("dashboards: failed to register MCP tool %s", name)
    return count
