"""Playlists — dashboards in a sequence, paged by hand or rotated on a timer.

A slide is a dashboard (``{"dashboard": slug}``) or a goal list
(``{"goals": slug}``). A goal list shows its goals against their targets now,
or with ``"show": "week"`` the week just ended (its snapshot, if saved), or
with ``"show": "weeks"`` the week-over-week grid (``weeks.py``).

The building blocks a downstream app uses to put a playlist anywhere:

- :func:`normalize_items` — validate and tidy ``Playlist.items`` (``clean()``
  calls it, so every surface is checked the same way).
- :func:`playlist_slides` — the slides *a viewer* gets: the dashboards they may
  open, each with its dwell time and period. A dashboard they can't open is
  skipped, never shown as an error, so a playlist doesn't reveal it exists.
- :func:`player_options` — what a link asks the player to do (``?slide=3&play=1``).
- :func:`player_context` — everything ``dashboards/includes/playlist_player.html``
  needs, the starting slide already rendered. ``{% playlist %}`` and the
  playlist page both use it; ``static/dashboards/js/playlist.js`` drives it.
- :func:`playlist_payload` — the same as JSON, for the REST route and MCP.

Link options (each also has a ``Playlist`` default where one makes sense):

=============  ==============================================================
``slide=N``    start on the N-th dashboard (1-based; clamped into range)
``play=1|0``   start playing / stay paused — overrides ``auto_start``
``seconds=N``  show every dashboard for N seconds (5–3600) this time
``loop=1|0``   wrap after the last dashboard — overrides ``loop``
``kiosk=1``    the page without the site's chrome, for a wall screen
=============  ==============================================================
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Optional

from django.http import HttpRequest
from django.urls import reverse

from .models import Dashboard, GoalList, Playlist

MAX_ITEMS = 50
MIN_SECONDS = 5
MAX_SECONDS = 3600
_ITEM_KEYS = {"dashboard", "goals", "show", "seconds", "period"}
#: What a goal-list slide shows: its goals now, last week, or week over week.
GOAL_SHOWS = {"now": "Goals now", "week": "Last week", "weeks": "Week over week"}


def normalize_items(items: Any, *, owner_id: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """``(items, problems)``. A bare slug becomes ``{"dashboard": slug}``;
    ``{"goals": slug}`` is a goal list.

    Each dashboard or goal list must exist and be one the playlist's owner
    can use: a shared one, or (for a personal playlist) the owner's own — the
    rule dashboards apply to metrics, so a shared playlist can't carry
    someone's personal dashboard to everyone."""
    from apps.datasets.dateranges import is_period

    if items in (None, ""):
        return [], []
    if not isinstance(items, list):
        return [], ["items must be a list of dashboards"]
    if len(items) > MAX_ITEMS:
        return [], [f"a playlist holds at most {MAX_ITEMS} dashboards"]
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    wanted = [i if isinstance(i, str) else (i.get("dashboard") if isinstance(i, dict) else None) for i in items]
    boards = {d.slug: d for d in Dashboard.objects.filter(slug__in=[w for w in wanted if isinstance(w, str)])}
    goal_slugs = [i.get("goals") for i in items if isinstance(i, dict) and isinstance(i.get("goals"), str)]
    goal_lists = {g.slug: g for g in GoalList.objects.filter(slug__in=goal_slugs)}
    for n, raw in enumerate(items, start=1):
        where = f"item {n}"
        item: dict[str, Any] = {"dashboard": raw} if isinstance(raw, str) else raw
        if not isinstance(item, dict):
            problems.append(f"{where}: must be a dashboard slug or an object")
            continue
        unknown = sorted(set(item) - _ITEM_KEYS)
        if unknown:
            problems.append(f"{where}: unknown key(s) {', '.join(unknown)}")
            continue
        if ("dashboard" in item) == ("goals" in item):
            problems.append(f"{where}: name a 'dashboard' or a 'goals' list (one of them)")
            continue
        clean: dict[str, Any]
        if "goals" in item:
            slug = item.get("goals")
            goal_list = goal_lists.get(slug) if isinstance(slug, str) else None
            if goal_list is None:
                problems.append(f"{where}: no goal list {slug!r}")
                continue
            if goal_list.owner_id is not None and goal_list.owner_id != owner_id:
                problems.append(f"{where}: {goal_list.name!r} is someone's personal goal list")
                continue
            clean = {"goals": goal_list.slug}
            show = item.get("show")
            if show not in (None, "", "now"):
                if show not in GOAL_SHOWS:
                    problems.append(f"{where}: show is one of {sorted(GOAL_SHOWS)}")
                    continue
                clean["show"] = show
        else:
            if item.get("show") not in (None, ""):
                problems.append(f"{where}: show is for goal lists")
                continue
            slug = item.get("dashboard")
            board = boards.get(slug) if isinstance(slug, str) else None
            if board is None:
                problems.append(f"{where}: no dashboard {slug!r}")
                continue
            if board.owner_id is not None and board.owner_id != owner_id:
                problems.append(f"{where}: {board.name!r} is someone's personal dashboard")
                continue
            clean = {"dashboard": board.slug}
        seconds = item.get("seconds")
        if seconds not in (None, ""):
            if isinstance(seconds, bool) or not isinstance(seconds, int | str) or not str(seconds).isdigit():
                problems.append(f"{where}: seconds must be a whole number")
                continue
            if not MIN_SECONDS <= int(seconds) <= MAX_SECONDS:
                problems.append(f"{where}: seconds must be between {MIN_SECONDS} and {MAX_SECONDS}")
                continue
            clean["seconds"] = int(seconds)
        period = item.get("period")
        if period not in (None, ""):
            if not isinstance(period, str) or not (period == "all" or is_period(period)):
                problems.append(f"{where}: {period!r} is not a known period")
                continue
            clean["period"] = period
        out.append(clean)
    return out, problems


def playlist_slides(playlist: Playlist, user: Any) -> list[dict[str, Any]]:
    """The slides *user* sees, in order: ``[{position, kind, dashboard,
    goal_list, slug, name, seconds, period, url}]``. ``kind`` is
    ``"dashboard"`` or ``"goals"`` (``dashboard`` / ``goal_list`` holds the
    object; the other is ``None``). ``period`` is the key the slide shows
    (``None`` = the item's own default, ``"all"`` = all time); ``url`` opens it
    on that period. Missing or unviewable items are left out."""
    boards = {d.slug: d for d in Dashboard.objects.filter(slug__in=playlist.dashboard_slugs())}
    goal_lists = {g.slug: g for g in GoalList.objects.filter(slug__in=playlist.goal_list_slugs())}
    slides: list[dict[str, Any]] = []
    for item in playlist.items:
        if not isinstance(item, dict):
            continue
        obj: Dashboard | GoalList | None
        if item.get("goals"):
            obj, kind = goal_lists.get(item["goals"]), "goals"
        else:
            obj, kind = boards.get(str(item.get("dashboard") or "")), "dashboard"
        if obj is None or not obj.can_view(user):
            continue
        period = item.get("period") or None
        show = (item.get("show") or "now") if kind == "goals" else ""
        url = obj.get_absolute_url() + (f"?period={period}" if period else "")
        name = obj.name
        if show in ("week", "weeks"):
            url = reverse("dashboards_goal_weeks", kwargs={"slug": obj.slug}) + (
                "?view=grid" if show == "weeks" else ""
            )
            name = f"{obj.name}, {GOAL_SHOWS[show].lower()}"
        slides.append(
            {
                "position": len(slides) + 1,
                "kind": kind,
                "dashboard": obj if kind == "dashboard" else None,
                "goal_list": obj if kind == "goals" else None,
                "slug": obj.slug,
                "name": name,
                **({"show": show} if kind == "goals" else {}),
                "seconds": int(item.get("seconds") or playlist.seconds),
                "period": period,
                "url": url,
            }
        )
    return slides


def _flag(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    value = value.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return None


def player_options(params: Mapping[str, str], playlist: Playlist, count: int) -> dict[str, Any]:
    """What a link asks for, resolved against the playlist's defaults:
    ``{start (0-based), play, loop, seconds (override or None), kiosk}``."""
    try:
        start = int(params.get("slide") or 1) - 1
    except ValueError:
        start = 0
    start = max(0, min(start, max(count - 1, 0)))
    play = _flag(params.get("play"))
    loop = _flag(params.get("loop"))
    seconds: Optional[int] = None
    raw = params.get("seconds")
    if raw and raw.isdigit():
        seconds = max(MIN_SECONDS, min(MAX_SECONDS, int(raw)))
    return {
        "start": start,
        "play": (playlist.auto_start if play is None else play) and count > 1,
        "loop": playlist.loop if loop is None else loop,
        "seconds": seconds,
        "kiosk": bool(_flag(params.get("kiosk"))),
    }


def slide_embed(slide: dict[str, Any], request: HttpRequest) -> dict[str, Any]:
    """One slide's context: a dashboard laid out with :func:`boards.board_embed`
    (CSS grid, lazy cells), or a goal list evaluated (:func:`goals.goals_embed`)."""
    from .boards import board_embed
    from .goals import goals_embed

    period = slide["period"]
    chosen = None if period is None else ("" if period == "all" else period)
    if slide.get("kind") == "goals":
        show = slide.get("show") or "now"
        if show == "week":
            from .weeks import this_week, week_page

            start = this_week() - timedelta(weeks=1)
            return {
                "goal_list": slide["goal_list"],
                "show": show,
                "week": week_page(slide["goal_list"], request, start),
            }
        if show == "weeks":
            from .weeks import this_week, week_grid

            return {
                "goal_list": slide["goal_list"],
                "show": show,
                "grid": week_grid(slide["goal_list"], request, this_week()),
            }
        return {**goals_embed(slide["goal_list"], request, period=chosen), "show": "now"}
    return board_embed(slide["dashboard"], request, period=chosen)


def player_context(
    playlist: Playlist, request: HttpRequest, params: Optional[Mapping[str, str]] = None, *, sync_url: bool = False
) -> dict[str, Any]:
    """The player include's context. *params* are the link options (the
    request's query string on the playlist page; the tag's arguments when
    embedded). ``sync_url`` keeps the address bar on the current slide —
    for the page that *is* the player, not for one embedded in another page."""
    slides = playlist_slides(playlist, request.user)
    params = params if params is not None else request.GET
    options = player_options(params, playlist, len(slides))
    current = slides[options["start"]] if slides else None
    count = len(slides)
    # The no-JS links (prev / next / steps): the player page itself, or the
    # playlist's page when embedded elsewhere; options the link set survive.
    kept = (
        (f"&seconds={options['seconds']}" if options["seconds"] else "")
        + (f"&loop={int(options['loop'])}" if _flag(params.get("loop")) is not None else "")
        + ("&kiosk=1" if options["kiosk"] else "")
    )
    return {
        "playlist": playlist,
        "slides": slides,
        "options": options,
        "current": current,
        "embed": slide_embed(current, request) if current else None,
        "slide_url": reverse("dashboards_playlist_slide", kwargs={"slug": playlist.slug, "position": 0}),
        "sync_url": sync_url,
        "skipped": len(playlist.items) - len(slides),
        "link_base": "" if sync_url else playlist.get_absolute_url(),
        "link_keep": kept,
        "prev_position": ((options["start"] - 1) % count) + 1 if count else 1,
        "next_position": ((options["start"] + 1) % count) + 1 if count else 1,
    }


def playlist_payload(playlist: Playlist, user: Any) -> dict[str, Any]:
    """The playlist as the viewer sees it, JSON-safe — for REST and MCP."""
    return {
        "slug": playlist.slug,
        "name": playlist.name,
        "url": playlist.get_absolute_url(),
        "seconds": playlist.seconds,
        "loop": playlist.loop,
        "auto_start": playlist.auto_start,
        "slides": [
            {k: v for k, v in s.items() if k not in ("dashboard", "goal_list")} for s in playlist_slides(playlist, user)
        ],
    }
