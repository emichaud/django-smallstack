"""The ``calendar`` dashboard card — a calendar embed as a card on any
dashboard, registered with the dashboards app's component registry from this
app's ``ready()`` the way a downstream app registers its own card types.

Options: ``calendars`` (comma-separated keys; a builder offers the ones its
user may see as a tick-list), ``mode`` (upcoming / month / board), ``days``
and ``limit``. The viewer's access is applied per calendar at render time; a
viewer who may see none of them gets the restricted card.
"""

from __future__ import annotations

import logging
from typing import Any

from .apps import CALENDAR_ICON_PATH
from .embed import MAX_UPCOMING_DAYS, MAX_UPCOMING_LIMIT, MODES, UPCOMING_DAYS, UPCOMING_LIMIT, clamp_int, split_keys

logger = logging.getLogger(__name__)

MODE_CHOICES = [["upcoming", "Upcoming"], ["month", "Month"], ["board", "Board"]]


def calendar_choices(user: Any) -> list[list[str]]:
    """``[[key, label]]`` for the calendars *user* may see: what a builder
    offers under Calendars, and what an agent reads the keys from."""
    from .core import list_calendars

    return [[c["key"], c["label"]] for c in list_calendars(user)]


def validate_calendar_card(cell: dict[str, Any]) -> list[str]:
    from .registry import get_spec

    opts = cell.get("options") or {}
    problems: list[str] = []
    keys = split_keys(opts.get("calendars"))
    if not keys:
        problems.append("'calendars' must name at least one calendar key (comma-separated)")
    for key in keys:
        if get_spec(key) is None:
            problems.append(f"'calendars': no calendar {key!r}")
    if opts.get("mode", "upcoming") not in MODES:
        problems.append(f"'mode' must be one of {', '.join(MODES)}")
    days = opts.get("days")
    if days not in (None, "") and clamp_int(days, -1, 1, MAX_UPCOMING_DAYS) != _int_or(days, -1):
        problems.append(f"'days' must be 1–{MAX_UPCOMING_DAYS}")
    limit = opts.get("limit")
    if limit not in (None, "") and clamp_int(limit, -1, 1, MAX_UPCOMING_LIMIT) != _int_or(limit, -1):
        problems.append(f"'limit' must be 1–{MAX_UPCOMING_LIMIT}")
    return problems


def _int_or(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def build_calendar_card(cell: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from apps.dashboards.components import cell_title

    from .embed import calendar_embed

    opts = cell.get("options") or {}
    mode = str(opts.get("mode") or "upcoming")
    embed = calendar_embed(
        ctx.request,
        opts.get("calendars"),
        mode=mode,
        lazy=False,
        days=clamp_int(opts.get("days"), UPCOMING_DAYS if mode == "upcoming" else 30, 1, MAX_UPCOMING_DAYS),
        limit=clamp_int(opts.get("limit"), UPCOMING_LIMIT, 1, MAX_UPCOMING_LIMIT),
    )
    label = cell_title(cell)
    if embed is None:
        return {"label": label or "Calendar", "restricted": True}
    return {"label": label, "embed": embed, "restricted": False}


def register() -> None:
    """Register the card type. A no-op when the dashboards app is absent."""
    try:
        from apps.dashboards.components import ComponentType, register_component_type
    except ImportError:
        return
    register_component_type(
        ComponentType(
            key="calendar",
            label="Calendar",
            description="Upcoming entries, a month grid or a day-range board from one or more calendars.",
            group="Info",
            icon=CALENDAR_ICON_PATH,
            media={"css": ["calendar/css/calendar.css"]},
            template="calendar/cells/calendar.html",
            build=build_calendar_card,
            default_size=(4, 4),
            # Its days can narrow other cards (options.publish): a day click sends
            # that day on a "date" field, which a listener maps to its own date column.
            publishes=True,
            validate=validate_calendar_card,
            options_schema=[
                {
                    "name": "calendars",
                    "label": "Calendars",
                    "type": "multichoice",
                    "required": True,
                    "choices": calendar_choices,
                    "help": "Tick each calendar the card draws. Someone viewing it sees only the ones they may open.",
                },
                {
                    "name": "mode",
                    "label": "Show",
                    "type": "choice",
                    "choices": MODE_CHOICES,
                    "default": "upcoming",
                    "widget": "segmented",
                    "help": "A list of what's coming, a month grid, or a day-range board.",
                },
                {
                    "name": "days",
                    "label": "Days ahead",
                    "type": "integer",
                    "default": UPCOMING_DAYS,
                    "min": 1,
                    "max": MAX_UPCOMING_DAYS,
                    "help": "The upcoming list's window; the board's range (30, 60 or 90).",
                },
                {
                    "name": "limit",
                    "label": "Rows",
                    "type": "integer",
                    "default": UPCOMING_LIMIT,
                    "min": 1,
                    "max": MAX_UPCOMING_LIMIT,
                    "help": "The most entries the upcoming list shows.",
                },
            ],
        )
    )
