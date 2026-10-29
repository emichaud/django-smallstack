"""MCP tools: discover calendars and pull a window of events.

Two site-level tools, mirroring ``list_datasets`` / ``query_dataset_*`` but
flattened — an agent asks "what's on the calendar between these dates?" far
more often than it asks about one dataset's time axis:

- ``list_calendars`` — the calendars the token's user may see.
- ``calendar_events`` — merged, normalised events for a list of calendars and
  an ISO date window (``end`` exclusive; defaults to the current month).

Access follows the page: any authenticated token may call them, and each
calendar's own ``access`` level decides whether it is visible to that user. A
staff calendar requested by a non-staff token is reported as unknown.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from django.http import HttpRequest, QueryDict

logger = logging.getLogger("smallstack.calendar")


def _fake_request(user: Any) -> HttpRequest:
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict("", mutable=False)
    req.META = {}
    return req


def _list_calendars_handler(args: dict[str, Any]) -> dict[str, Any]:
    from apps.mcp.server import current_context

    from .core import list_calendars

    ctx = current_context()
    return {"results": list_calendars(getattr(ctx, "user", None))}


def _calendar_events_handler(args: dict[str, Any]) -> dict[str, Any]:
    from django.utils import timezone

    from apps.mcp.server import current_context

    from .api import max_window_days
    from .core import collect_events, month_bounds, resolve_keys

    ctx = current_context()
    user = getattr(ctx, "user", None)
    keys = args.get("calendars") or []
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(",") if k.strip()]
    if not keys:
        return {"error": "calendars is required — use list_calendars to find keys"}
    cals, rejected = resolve_keys([str(k) for k in keys], user)
    if rejected:
        return {"error": f"unknown calendar(s): {', '.join(rejected)}"}

    today = timezone.localdate()
    lower, upper = month_bounds(today)
    try:
        if args.get("start"):
            lower = date.fromisoformat(str(args["start"]))
            upper = lower + timedelta(days=31)
        if args.get("end"):
            upper = date.fromisoformat(str(args["end"]))
    except ValueError as exc:
        return {"error": f"bad date: {exc}"}
    if upper <= lower:
        return {"error": "end must be after start"}
    if (upper - lower).days > max_window_days():
        return {"error": f"window exceeds {max_window_days()} days"}

    limit = args.get("limit") or 200
    events, counts, capped = collect_events(cals, lower, upper, _fake_request(user), limit=None)
    rows = [ev.as_dict() for ev in events]
    return {
        "start": lower.isoformat(),
        "end": upper.isoformat(),
        "calendars": [c.key for c in cals],
        "counts": counts,
        "total": len(rows),
        "count": min(len(rows), int(limit)),
        "results": rows[: int(limit)],
    }


def register_calendar_tools() -> int:
    """Register the two tools. No-op when ``apps.mcp`` is unavailable."""
    try:
        from apps.mcp.server import tool
    except Exception:
        logger.info("apps.mcp not available — skipping calendar MCP tools")
        return 0

    count = 0
    try:
        tool(
            "list_calendars",
            (
                "List the calendars (datasets with a date axis) this site offers you: "
                "{key, label, description, start, end, ranged}. Pass keys to calendar_events."
            ),
            {"type": "object", "properties": {}, "additionalProperties": False},
            requires_access="readonly",
        )(_list_calendars_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register list_calendars MCP tool")

    try:
        tool(
            "calendar_events",
            (
                "Events from one or more calendars in a date window, merged and sorted by start. "
                "Each event: {calendar, id, title, subtitle, start, end, all_day, status, url}. "
                "Dates are ISO; end is exclusive; the default window is the current month."
            ),
            {
                "type": "object",
                "properties": {
                    "calendars": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Calendar keys from list_calendars.",
                    },
                    "start": {"type": "string", "description": "ISO date (inclusive)."},
                    "end": {"type": "string", "description": "ISO date (exclusive)."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 1000,
                        "default": 200,
                        "description": "Max events to return.",
                    },
                },
                "required": ["calendars"],
                "additionalProperties": False,
            },
            requires_access="readonly",
        )(_calendar_events_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register calendar_events MCP tool")
    return count
