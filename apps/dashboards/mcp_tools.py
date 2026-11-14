"""MCP tools for building dashboards and KPIs agentically.

The CRUD (``create_metric`` / ``update_dashboard`` / ``list_reports`` …) is
generated from the CRUDViews. These add what CRUD can't:

- ``list_dashboard_components`` — the card types, their options, the periods
- ``metric_preview``   — dry-run an unsaved metric: value + row count + every problem
- ``metric_value``     — evaluate a saved metric (optionally for a period)
- ``metric_trend``     — a saved metric per day / week / month / quarter / year across a period (what a chart reads)
- ``metric_usage``     — where a metric is used, before an edit or delete
- ``metric_record_value`` / ``metric_delete_value`` — a hand-entered metric's values
- ``metric_rows``      — the rows behind a saved metric's number
- ``dashboard_snapshot`` — every card on a dashboard, evaluated (check your work)
- ``dashboard_add_card`` / ``dashboard_remove_card`` — edit one card, not the whole layout (or place a saved one)
- ``card_preview``     — render an unsaved card (the component builder's dry run)
- ``dashboard_share`` — who may open a personal dashboard: everyone, or people by username
- ``dashboard_set_picture`` — the dashboard's picture, sent as base64 (or removed)
- ``report_values``    — a report's matrix
- ``playlist_slides``  — a playlist as the caller sees it (the CRUD tools create and edit one)
- ``goal_list_values`` — a goal list judged: each goal's value, status (on target / at risk / missed), target
- ``goal_list_add_goal`` — append one goal to a section of a goal list
- ``goal_list_weeks``  — a goal list week over week (saved snapshots, or worked out)
- ``goal_list_save_week`` — save a week's values and targets (or fill past weeks)
- ``goal_list_tracking`` / ``goal_list_capture`` / ``goal_list_history`` — which cadences are captured,
  capture now (or fill past periods), read the captures

The intended loop: ``list_datasets`` → ``describe_dataset`` → ``metric_preview``
(until ``problems`` is empty and the number is plausible) → ``create_metric`` →
``create_dashboard`` → ``dashboard_add_card`` × N → ``dashboard_snapshot``.

Every tool reads as the token's user: ownership (``can_view`` / ``can_edit``)
and each dataset's ``access`` tier apply exactly as on the pages.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

_CADENCES = ["hourly", "daily", "weekly", "monthly", "quarterly"]


def _user() -> Any:
    from apps.mcp.server import current_context

    return getattr(current_context(), "user", None)


def _components(args: dict[str, Any]) -> dict[str, Any]:
    from .components import components_payload

    payload = components_payload(_user())
    # The palette's drawing assets are for the page's builder, not an agent.
    for card_type in payload["types"]:
        card_type.pop("icon", None)
        card_type.pop("media", None)
    # Options every data card takes beside its own: an agent found these only
    # by sending bad values until the validator named them.
    payload["shared_options"] = {
        "publish": 'A channel name ("method"): a click on this card (types with publishes: true) narrows '
        "every card listening to that channel.",
        "listen": '{"channel": "<name>", "map"?: {"<their column>": "<my column>"}}: narrow this card to '
        "what's clicked on the channel; map only when the columns are named differently.",
        "style": '{"format": "number|compact|decimal|percent|currency|duration", "unit": "ms"} for a card '
        "with its own source.",
        "thresholds": "Colour rules for a card with its own source, as a metric's thresholds.",
    }
    return payload


def _integer(value: Any, name: str) -> tuple[Any, Any]:
    """``(int or None, error dict or None)`` for an optional integer argument."""
    if value in (None, ""):
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, {"error": f"{name} must be a whole number, not {value!r}"}


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
    from .periods import NO_PERIOD_FIELD_NOTE, period_problem

    period = str(args.get("period") or "") or None
    problem = period_problem(period)
    if problem:
        return {"error": problem}
    req = request_for(user)
    result = evaluate(metric, req, period=period)
    out = {
        "key": metric.key,
        "name": metric.name,
        "url": metric.get_absolute_url(),
        **result.as_dict(),
        # The pages' comparison: this period against the one before it (null
        # for all time or a rolling window — they have no defined predecessor).
        "comparison": compare_with_previous(metric, req, period, result),
    }
    if period and period != "all" and not metric.period_field:
        out["note"] = NO_PERIOD_FIELD_NOTE
    return out


def _metric_trend(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .models import Metric
    from .trends import metric_trend

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    from apps.datasets.core import GRAINS

    from .periods import period_problem

    period = str(args.get("period") or "") or None
    grain = str(args.get("grain") or "") or None
    problem = period_problem(period)
    if problem:
        return {"error": problem}
    if grain and grain not in GRAINS:
        return {"error": f"unknown grain {grain!r} — use one of {', '.join(GRAINS)}"}
    if period == "all":
        period = None
    trend = metric_trend(metric, request_for(user), period, grain)
    return {"key": metric.key, "name": metric.name, **trend}


def _dashboard(user: Any, slug: Any) -> Any:
    from .models import Dashboard

    dashboard = Dashboard.objects.filter(slug=str(slug or "")).first()
    if dashboard is None or not dashboard.can_view(user):
        return None
    return dashboard


def _snapshot(args: dict[str, Any]) -> dict[str, Any]:
    from .boards import board_values
    from .metrics import request_for
    from .periods import period_problem

    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    raw = args.get("period")
    problem = period_problem(raw)
    if problem:
        return {"error": problem}
    period = dashboard.default_period or None if raw is None else (raw if raw not in ("", "all") else None)
    return {
        "slug": dashboard.slug,
        "name": dashboard.name,
        "url": dashboard.get_absolute_url(),
        "period": period,
        "cells": board_values(dashboard, request_for(user), period),
        **_link_warnings(dashboard.layout),
    }


def _link_warnings(layout: Any) -> dict[str, Any]:
    from .components import link_warnings

    found = link_warnings(layout)
    return {"warnings": found} if found else {}


def _add_card(args: dict[str, Any]) -> dict[str, Any]:
    from django.core.exceptions import ValidationError

    from .components import SOURCE_KEYS, get_component_type, next_position

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
    if component is None and not args.get("type"):
        return {"error": "give component (a saved card's key) or type (list_dashboard_components lists them)"}
    ct = get_component_type(component.type if component else str(args.get("type") or ""))
    if ct is None:
        return {"error": f"unknown type {args.get('type')!r} — use list_dashboard_components"}
    sizes = {}
    for name in ("w", "h", "x", "y"):
        sizes[name], problem = _integer(args.get(name), name)
        if problem:
            return problem
    w = sizes["w"] or ct.default_size[0]
    h = sizes["h"] or ct.default_size[1]
    x, y = next_position(dashboard.layout, w)
    cell: dict[str, Any] = {
        "x": sizes["x"] if sizes["x"] is not None else x,
        "y": sizes["y"] if sizes["y"] is not None else y,
        "w": w,
        "h": h,
    }
    if component is not None:
        cell["component"] = component.key  # its type, metric and options come from the saved card
        placed_keys: tuple[str, ...] = ("title", "id")
    else:
        cell["type"] = ct.key
        placed_keys = ("metric", *SOURCE_KEYS, "title", "options", "id")
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
    return {
        "ok": True,
        "cell": added,
        "url": dashboard.get_absolute_url(),
        "cells": len(dashboard.layout),
        **_link_warnings(dashboard.layout),
    }


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


def _share(args: dict[str, Any]) -> dict[str, Any]:
    from .boards import set_sharing, share_payload

    user = _user()
    dashboard = _dashboard(user, args.get("dashboard"))
    if dashboard is None:
        return {"error": f"no dashboard {args.get('dashboard')!r} — use list_dashboards"}
    if not dashboard.can_edit(user):
        return {"error": "you may not edit this dashboard"}
    if dashboard.owner_id is None:
        return {**share_payload(dashboard), "note": "an ownerless dashboard is everyone's already; nothing to set"}
    everyone = args.get("everyone")
    add, remove = args.get("add") or [], args.get("remove") or []
    if everyone is None and not add and not remove:
        return share_payload(dashboard)  # just asking
    if not isinstance(add, list) or not isinstance(remove, list):
        return {"error": "add and remove are lists of usernames"}
    from django.contrib.auth import get_user_model

    User = get_user_model()
    known = {u.get_username() for u in User.objects.filter(is_active=True, username__in=[*add, *remove])}
    unknown = sorted(set(map(str, [*add, *remove])) - known)
    out = set_sharing(dashboard, actor=user, everyone=everyone, add=add, remove=remove)
    if unknown:
        # ok: true with nobody added read as done; say what happened.
        out["unknown"] = unknown
        missed = f"no active user named {', '.join(map(repr, unknown))} (usernames are case-sensitive)"
        out["warning"] = f"{out['warning']}; {missed}" if out.get("warning") else missed
    return out


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
    if args.get("week") and parse_week(args.get("week")) is None:
        return {"error": f"unknown week {args['week']!r} — use a date (2026-11-02) or an ISO week (2026-W45)"}
    weeks, problem = _integer(args.get("weeks"), "weeks")
    if problem:
        return problem
    count = max(1, min(weeks or GRID_WEEKS, 26))
    return weeks_payload(goal_list, week_grid(goal_list, request_for(user), min(last, this_week()), count))


def _goal_list_save_week(args: dict[str, Any]) -> dict[str, Any]:
    from .models import GoalList
    from .weeks import backfill, parse_week, take_snapshot, this_week

    user = _user()
    goal_list = GoalList.objects.filter(slug=str(args.get("goal_list") or "")).first()
    if goal_list is None or not goal_list.can_view(user):
        return {"error": f"no goal list {args.get('goal_list')!r} — use list_goal_lists"}
    if not goal_list.can_edit(user):
        return {"error": "you can view this goal list but not edit it"}
    fill, problem = _integer(args.get("fill"), "fill")
    if problem:
        return problem
    if fill:
        done = backfill(goal_list, fill, by=user)
        total = goal_list.snapshots.filter(cadence="weekly").order_by().values("period_start").distinct().count()
        return {"ok": True, "saved_weeks": done, "total_saved": total}
    start = parse_week(args.get("week")) if args.get("week") else this_week() - timedelta(weeks=1)
    if start is None:
        return {"error": f"unknown week {args['week']!r} — use a date (2026-11-02) or an ISO week (2026-W45)"}
    try:
        snapshot = take_snapshot(goal_list, start, by=user)
    except ValueError as exc:
        return {"error": str(exc)}
    return {
        "ok": True,
        "week": snapshot.week_start.isoformat(),
        "summary": snapshot.summary,
        "complete": snapshot.complete,
    }


def _goal_list_for(args: dict[str, Any], *, edit: bool = False) -> tuple[Any, Any]:
    """``(goal list, None)``, or ``(None, an error answer)``."""
    from .models import GoalList

    user = _user()
    goal_list = GoalList.objects.filter(slug=str(args.get("goal_list") or "")).first()
    if goal_list is None or not goal_list.can_view(user):
        return None, {"error": f"no goal list {args.get('goal_list')!r} — use list_goal_lists"}
    if edit and not goal_list.can_edit(user):
        return None, {"error": "you can view this goal list but not edit it"}
    return goal_list, None


def _goal_list_tracking(args: dict[str, Any]) -> dict[str, Any]:
    from .snapshots import set_tracking, tracked_cadences

    wanted = args.get("cadences")
    goal_list, problem = _goal_list_for(args, edit=wanted is not None)
    if problem:
        return problem
    if wanted is None:
        return {"goal_list": goal_list.slug, "tracked": tracked_cadences(goal_list)}
    try:
        return {"goal_list": goal_list.slug, "tracked": set_tracking(goal_list, wanted, by=_user())}
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}


def _goal_list_capture(args: dict[str, Any]) -> dict[str, Any]:
    from .snapshots import capture, current_period, fill

    goal_list, problem = _goal_list_for(args, edit=True)
    if problem:
        return problem
    count, bad = _integer(args.get("fill"), "fill")
    if bad:
        return bad
    if args.get("fill") is not None and count < 1:
        return {"error": "fill is how many past periods to capture: 1 or more. Leave it out for the current period."}
    try:
        if count:
            replace = bool(args.get("replace"))
            done = fill(goal_list, str(args.get("cadence")), count, by=_user(), replace_existing=replace)
            return {"ok": True, "captured": done}
        snapshot = capture(goal_list, current_period(str(args.get("cadence"))), by=_user())
    except (ValueError, KeyError) as exc:
        return {"error": str(exc) if isinstance(exc, ValueError) else f"unknown cadence {args.get('cadence')!r}"}
    return {"ok": True, "period": snapshot.period_start.isoformat(), "summary": snapshot.summary}


def _goal_list_history(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import request_for
    from .snapshots import history_grid, history_payload

    goal_list, problem = _goal_list_for(args)
    if problem:
        return problem
    try:
        return history_payload(goal_list, history_grid(goal_list, request_for(_user()), str(args.get("cadence"))))
    except (ValueError, KeyError):
        return {"error": f"unknown cadence {args.get('cadence')!r} — hourly, daily, weekly, monthly or quarterly"}


def _metric_usage(args: dict[str, Any]) -> dict[str, Any]:
    from .models import Metric, metric_usage

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    usage = metric_usage(metric, user)

    def places(rows: list[dict[str, Any]], count: str) -> list[dict[str, Any]]:
        return [
            {"name": r["obj"].name, "slug": r["obj"].slug, count: r[count], "can_edit": r["can_edit"]} for r in rows
        ]

    return {
        "key": metric.key,
        "dashboards": places(usage["boards"], "cards"),
        "reports": places(usage["reports"], "rows"),
        "goal_lists": places(usage["goal_lists"], "goals"),
        "saved_cards": [c.key for c in usage["components"]],
        "rates": [m.key for m in usage["rates"]],
    }


def _record_value(args: dict[str, Any]) -> dict[str, Any]:
    from .entries import parse_entry, record_entry
    from .models import Metric

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    if not metric.can_edit(user):
        return {"error": f"you can't edit {metric.key!r}"}
    if not metric.is_manual:
        return {"error": f"{metric.key!r} isn't entered by hand (its source is {metric.source})"}
    day, value, errors = parse_entry(args.get("date"), args.get("value"))
    if errors or day is None or value is None:
        return {"error": "; ".join(errors.values())}
    entry = record_entry(metric, day, value, str(args.get("note") or ""), by=user)
    return {"key": metric.key, "date": entry.date.isoformat(), "value": float(entry.value), "note": entry.note}


def _delete_value(args: dict[str, Any]) -> dict[str, Any]:
    from datetime import date

    from .entries import delete_entry
    from .models import Metric

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    if not metric.can_edit(user):
        return {"error": f"you can't edit {metric.key!r}"}
    if not metric.is_manual:
        return {"error": f"{metric.key!r} isn't entered by hand (its source is {metric.source})"}
    try:
        day = date.fromisoformat(str(args.get("date") or ""))
    except ValueError:
        return {"error": "date must be YYYY-MM-DD"}
    return {"key": metric.key, "date": day.isoformat(), "deleted": delete_entry(metric, day)}


def _metric_rows(args: dict[str, Any]) -> dict[str, Any]:
    from .metrics import drill_rows, may_read, request_for
    from .models import Metric
    from .periods import period_problem

    user = _user()
    metric = Metric.objects.filter(key=str(args.get("key") or "")).first()
    if metric is None or not metric.can_view(user):
        return {"error": f"no metric {args.get('key')!r} — use list_metrics"}
    if not may_read(metric, user):
        return {"error": "you don't have access to this metric's data"}
    period = str(args.get("period") or "") or None
    problem = period_problem(period)
    if problem:
        return {"error": problem}
    limit, problem = _integer(args.get("limit"), "limit")
    if problem:
        return problem
    if limit is not None and limit < 1:
        return {"error": f"limit must be at least 1, not {limit}"}
    order = str(args.get("order") or "")
    from apps.datasets.core import get_dataset

    ds = get_dataset(metric.dataset)
    columns = ds.column_names() if ds is not None else []
    if order and order.lstrip("-") not in columns:
        return {"error": f"unknown order {order!r} — a column of {metric.dataset}: {', '.join(columns)}"}
    try:
        return drill_rows(
            metric,
            request_for(user),
            period=None if period == "all" else period,
            limit=min(limit or 25, 200),
            order=order,
        )
    except ValueError as exc:
        return {"error": str(exc)}


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
    keys = ("metric", "component", "label", "target", "warn", "targets", "period", "note")
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
    # The same table as a file, for a person with access: the page's Download CSV.
    out["csv_url"] = f"{out['url']}?format=csv"
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

    from .metrics import all_aggs_available

    obj = "object"
    agg_names = [key for key, _label in all_aggs_available()]
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
                    "source": {
                        "type": "string",
                        "enum": ["dataset", "manual", "rate"],
                        "description": "Where the number comes from. Default dataset.",
                    },
                    "numerator": {"type": "string", "description": "A rate's top: a metric key."},
                    "denominator": {"type": "string", "description": "A rate's bottom: a metric key."},
                    "dataset": {"type": "string", "description": "Dataset key (list_datasets)."},
                    "filter_tree": {"type": "object", "description": _FILTER_TREE_DOC},
                    "agg": {"type": "string", "enum": agg_names},
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
            "metric_usage",
            "Where a saved metric is used: the dashboards, reports, goal lists and saved cards that would "
            "change if it were edited or deleted. delete_metric removes the metric from all of them, so read "
            "this first.",
            {
                "type": obj,
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
                "additionalProperties": False,
            },
            _metric_usage,
            False,
        ),
        (
            "goal_list_tracking",
            "Read which cadences a goal list is captured on, or set them with cadences (any of hourly, daily, "
            "weekly, monthly, quarterly). Each tracked period is captured once it ends. Turning one off keeps "
            "what it captured. Needs write access even to read; goal_list_history also answers tracked.",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string"},
                    "cadences": {"type": "array", "items": {"type": "string", "enum": _CADENCES}},
                },
                "required": ["goal_list"],
                "additionalProperties": False,
            },
            _goal_list_tracking,
            True,
        ),
        (
            "goal_list_capture",
            "Capture a goal list for the current period of a cadence, adding to any earlier captures. With fill, "
            "capture that many past periods that have no finished capture, against today's targets, up to 48 "
            "hours, 60 days, 26 weeks, 24 months or 12 quarters. The same store as goal_list_save_week, which "
            "saves one named week; goal_list_weeks and goal_list_history read it back.",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string"},
                    "cadence": {"type": "string", "enum": _CADENCES},
                    "fill": {"type": "integer", "minimum": 1},
                    "replace": {
                        "type": "boolean",
                        "description": "With fill: add a new capture to periods that already have one, judged against "
                        "today's targets. Use it after fixing a target. Earlier captures stay.",
                    },
                },
                "required": ["goal_list", "cadence"],
                "additionalProperties": False,
            },
            _goal_list_capture,
            True,
        ),
        (
            "goal_list_history",
            "A goal list's captured values for one cadence: goals down, recent periods across. Only what was "
            "captured: a period with none is null, never worked out now.",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string"},
                    "cadence": {"type": "string", "enum": _CADENCES},
                },
                "required": ["goal_list", "cadence"],
                "additionalProperties": False,
            },
            _goal_list_history,
            False,
        ),
        (
            "metric_record_value",
            "Set a hand-entered metric's value for a date, replacing any earlier value and note for that date. "
            "Adds a new capture of each saved day, week, month or quarter holding that date, keeping its target. "
            "Only for a metric whose source is manual.",
            {
                "type": obj,
                "properties": {
                    "key": {"type": "string"},
                    "date": {"type": "string", "description": "The day it's for, YYYY-MM-DD. Not in the future."},
                    "value": {"type": "number"},
                    "note": {"type": "string", "description": "Where it came from (optional, up to 200 characters)."},
                },
                "required": ["key", "date", "value"],
                "additionalProperties": False,
            },
            _record_value,
            True,
        ),
        (
            "metric_delete_value",
            "Remove a hand-entered metric's value for a date. deleted says whether there was one. Only for a "
            "metric whose source is manual.",
            {
                "type": obj,
                "properties": {"key": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD."}},
                "required": ["key", "date"],
                "additionalProperties": False,
            },
            _delete_value,
            True,
        ),
        (
            "metric_rows",
            "The rows behind a saved metric's number: {columns, rows, total}, where total equals a count "
            "metric's value. Use it to explain a number (which paths, whose tickets). Optional period; order is "
            "a column, '-' for descending; limit 1-200 (default 25).",
            {
                "type": obj,
                "properties": {
                    "key": {"type": "string"},
                    "period": {"type": "string", "description": "A period key, e.g. pwtd, last_30, or 'all'."},
                    "order": {"type": "string", "description": "A column, e.g. -timestamp."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["key"],
                "additionalProperties": False,
            },
            _metric_rows,
            False,
        ),
        (
            "dashboard_snapshot",
            "Every card on a dashboard with its live value, to check a dashboard you built; nothing is stored. "
            "A chart or calendar card has no one number, so it lists with none: card_preview draws it, and "
            "calendar_events gives the dates. Optional period (default: the dashboard's own).",
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
            "Append one card to a dashboard (at the end of the last row, or below it when it doesn't fit, unless "
            "x/y are given). Either "
            "component = a saved card's key (list_components; its design stays in step when the card is edited), "
            "or an inline card: type from list_dashboard_components, plus its source. A card that draws data "
            "filters a dataset of its own: dataset (list_datasets) + filter_tree (metric_preview's shape) + "
            "agg/measure + period_field (the date column the period narrows and a chart buckets by). A single-value "
            "design (single_value: true in list_dashboard_components: metric, gauge) may instead draw a saved "
            "metric: metric = its key; a design that doesn't split into groups (trend) may draw a hand-entered or "
            "rate metric. "
            'options per type (metric_group: {"dimension": "<column>", "limit": 5}; text: {"markdown": "..."}; '
            'widget: {"widget": "<key>"}); a card with its own source formats itself through options.style '
            "({format, unit}) and options.thresholds. Link cards so a click on one narrows others: "
            'options.publish: "<channel>" on the clicked card, options.listen: {"channel": "<channel>"} on the '
            "others (list_dashboard_components: shared_options). An option the type doesn't take is refused; a "
            "channel with only one end comes back in warnings.",
            {
                "type": obj,
                "properties": {
                    "dashboard": {"type": "string", "description": "Dashboard slug."},
                    "component": {
                        "type": "string",
                        "description": "A saved card's key, instead of type/metric/options.",
                    },
                    "type": {"type": "string"},
                    "metric": {"type": "string", "description": "A saved metric's key: single-value designs only."},
                    "dataset": {"type": "string", "description": "The card's own source: a dataset key."},
                    "filter_tree": {"type": "object", "description": "The card's own filter over its dataset."},
                    "agg": {
                        "type": "string",
                        "description": "count | distinct | sum | avg | median | min | max (all but count need a "
                        "measure; median only where the database has one).",
                    },
                    "measure": {"type": "string", "description": "The column agg reads (not for count)."},
                    "period_field": {"type": "string", "description": "The date column the period narrows."},
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
            "dashboard_share",
            "Who may open a personal dashboard (its owner still edits it). With no change requested, reports "
            "the current sharing: everyone (true = everyone who can sign in) and people (usernames). Set "
            "everyone, or add / remove people by username; each person added gets a notification with the link. "
            "A viewer reads the dashboard's cards as the owner sees them, except data their own access doesn't "
            "reach: the reply's cant_read ({username: [card titles]}) and warning name cards a person added can't "
            "read. An ownerless (shared) dashboard is everyone's already.",
            {
                "type": obj,
                "properties": {
                    "dashboard": {"type": "string", "description": "Dashboard slug."},
                    "everyone": {"type": "boolean"},
                    "add": {"type": "array", "items": {"type": "string"}, "description": "Usernames to share with."},
                    "remove": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["dashboard"],
                "additionalProperties": False,
            },
            _share,
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
            "Render an UNSAVED card (dry run): {type, its source (dataset + filter_tree + agg/measure/period_field, "
            "or metric for a single stat), options?, name?, period?, visibility?} → {html, problems}. Validated "
            "exactly as a dashboard cell; iterate until problems is empty, then create_component with the same "
            "fields to save it.",
            {
                "type": obj,
                "properties": {
                    "type": {"type": "string"},
                    "metric": {"type": "string"},
                    "dataset": {"type": "string"},
                    "filter_tree": {"type": "object"},
                    "agg": {"type": "string"},
                    "measure": {"type": "string"},
                    "period_field": {"type": "string"},
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
            "goal_list_save_week",
            "Save a week of a goal list, keeping its values, statuses and targets as they are now, so later "
            "target changes don't rewrite it (the page's Save this week). Default: the week just ended, which "
            "the schedule also saves each Monday. fill: N saves the past N weeks that aren't saved yet instead. "
            "Needs edit rights on the list.",
            {
                "type": obj,
                "properties": {
                    "goal_list": {"type": "string", "description": "Goal list slug."},
                    "week": {"type": "string", "description": "Any day of the week (YYYY-MM-DD) or 2026-W45."},
                    "fill": {"type": "integer", "description": "Save this many unsaved past weeks instead."},
                },
                "required": ["goal_list"],
                "additionalProperties": False,
            },
            _goal_list_save_week,
            True,
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
                    "targets": {
                        "type": obj,
                        "description": "Targets for particular cadences, used by weeks and history: "
                        '{"hourly": {"target": {"op": ">=", "value": 10}, "warn": {...}}}. Without one, weekly and '
                        "averages, rates and readings use the main target; a count or sum isn't judged.",
                    },
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
            "Evaluate a KPI report: one row per metric, one column per period. url and csv_url are the report's "
            "page and its CSV download, relative to the site, for a signed-in person to open. Over REST, "
            "dashboards/api/reports/<slug>/values/?format=csv is the CSV with a token.",
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
