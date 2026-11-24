"""Dashboards at run time — a stored layout turned into cards and values.

- :func:`render_cell` — one cell's HTML through the component registry. The
  one rendering seam: the dashboard page's lazy cells use it, and so can a
  downstream page that shows a dashboard its own way.
- :func:`board_values` — every cell evaluated, as JSON (REST + MCP).
- :func:`board_attention` — the cells whose threshold says look at me.
- :func:`board_embed` — a dashboard laid out for any page (``{% dashboard %}``).
- :func:`board_cards` / :func:`cell_value` — its cards as table rows, and one
  card's headline value (the settings page's table).

Each takes the ``request`` whose user the numbers are for; a cell the user
may not read renders or reports as restricted, never as a number.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Optional

from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.safestring import SafeString, mark_safe

from apps.datasets.filter_tree import FilterTreeError, and_trees

from .components import (
    CellContext,
    cell_source,
    cell_title,
    get_component_type,
    inline_source,
    is_inline,
    listened_narrow,
    source_rows_url,
)
from .forms import DashboardPictureForm
from .metrics import evaluate, group_values, may_read
from .models import Dashboard, Metric, metric_key_from_name
from .periods import period_heading

logger = logging.getLogger(__name__)


def cell_period(cell: dict[str, Any], period: Optional[str]) -> Optional[str]:
    """The period *cell* evaluates for: the dashboard's, unless the cell is
    pinned to all time (``use_period: false``)."""
    return period if cell.get("use_period", True) is not False else None


def render_cell(
    dashboard: Dashboard, cell: dict[str, Any], request: HttpRequest, period: Optional[str], narrow: str = ""
) -> str:
    """One cell's inner HTML. Never raises for a broken cell — an unknown
    type, a deleted metric or a failing build renders an error card instead,
    so one bad cell can't take the dashboard down."""
    ct = get_component_type(str(cell.get("type", "")))
    base: dict[str, Any] = {"cell": cell, "dashboard": dashboard, "request": request}
    if ct is None:
        return render_to_string(
            "dashboards/cells/error.html",
            {**base, "message": f"Unknown card type “{cell.get('type')}”."},
            request=request,
        )
    user = request.user
    if ct.visible_to is not None and not ct.visible_to(user):
        return render_to_string("dashboards/cells/restricted.html", {**base, "label": cell_title(cell) or ct.label})
    metric = None
    if ct.needs_metric:
        metric = cell_source(cell)
        if metric is None:
            gone = "This card has no source."
            if cell.get("metric"):
                gone = f"Metric “{cell.get('metric')}” no longer exists."
            return render_to_string("dashboards/cells/error.html", {**base, "message": gone}, request=request)
        if not may_read(metric, user):
            return render_to_string(
                "dashboards/cells/restricted.html", {**base, "label": cell_title(cell) or metric.name}
            )
    period = cell_period(cell, period)
    # A slice another card sent this one (options.listen): checked against its
    # data, then AND-ed onto a copy of its source, so every number, group, bucket
    # and row it draws is narrowed alike; refused with a reason, never dropped.
    sliced = None
    if narrow:
        sliced, problem = listened_narrow(cell, narrow, metric)
        if problem:
            return render_to_string("dashboards/cells/error.html", {**base, "message": problem}, request=request)
        if metric is not None and sliced:
            metric = copy.copy(metric)
            metric.filter_tree = and_trees(metric.filter_tree, sliced)
    ctx = CellContext(
        request=request,
        dashboard=dashboard,
        metric=metric,
        period=period,
        rows_url=source_rows_url(dashboard, cell, metric, user),
        narrow=sliced,
    )
    try:
        context = ct.build(cell, ctx)
    except Exception:  # noqa: BLE001 — a component's bug must not take the page down
        logger.exception("dashboard %s cell %s failed", dashboard.slug, cell.get("id"))
        return render_to_string(
            "dashboards/cells/error.html", {**base, "message": "This card failed to render."}, request=request
        )
    return render_to_string(ct.template, {**base, **context, "period": period}, request=request)


def _groups(metric: Metric, cell: dict[str, Any], request: HttpRequest, period: Optional[str], *, other: bool) -> list:
    opts = cell.get("options") or {}
    return group_values(
        metric,
        request,
        str(opts.get("dimension") or ""),
        limit=int(opts.get("limit", 5) or 5),
        other=other,
        period=period,
    )


def board_values(dashboard: Dashboard, request: HttpRequest, period: Optional[str]) -> list[dict[str, Any]]:
    """Every cell, evaluated: its placement plus ``result`` (a metric card),
    ``groups`` (a grouped card), ``markdown`` (a note), ``restricted`` or
    ``error``. What an agent reads to check the dashboard it built."""
    out = []
    for cell in dashboard.layout:
        entry: dict[str, Any] = {k: cell.get(k) for k in ("id", "type", "metric", "title", "x", "y", "w", "h")}
        ct = get_component_type(str(cell.get("type", "")))
        metric = cell_source(cell)
        if metric is not None and is_inline(metric):
            entry["dataset"] = metric.dataset
        when = cell_period(cell, period)
        if ct is None:
            entry["error"] = "unknown component type"
        elif ct.needs_metric and metric is None:
            entry["error"] = "metric no longer exists" if cell.get("metric") else "no source"
        elif metric is not None and (cell.get("type") == "metric" or ct.single_value):
            # Any one-number design (a gauge too) has its number to check.
            entry["result"] = evaluate(metric, request, period=when).as_dict()
        elif metric is not None and cell.get("type") == "metric_group":
            if not may_read(metric, request.user):
                entry["restricted"] = True
            else:
                other = (cell.get("options") or {}).get("other", True) is not False
                try:
                    groups = _groups(metric, cell, request, when, other=other)
                    entry["groups"] = [
                        {k: g.get(k) for k in ("label", "value", "display", "state", "other")} for g in groups
                    ]
                except ValueError as exc:
                    entry["error"] = str(exc)
        elif cell.get("type") == "goals":
            from .goals import goal_values
            from .models import GoalList

            goal_list = GoalList.objects.filter(slug=(cell.get("options") or {}).get("goal_list") or "").first()
            if goal_list is None:
                entry["error"] = "goal list no longer exists"
            elif not goal_list.can_view(request.user):
                entry["restricted"] = True
            else:
                entry["goals"] = goal_values(goal_list, request, period=when or "")
        elif cell.get("type") == "text":
            entry["markdown"] = (cell.get("options") or {}).get("markdown", "")
        out.append(entry)
    return json.loads(json.dumps(out, default=str))


def board_attention(dashboard: Dashboard, request: HttpRequest, period: Optional[str]) -> dict[str, Any]:
    """Which metric cards need attention at *period*: ``{attention: [{name,
    state, display}], fine, rated, when}``. ``attention`` holds the cards (and
    grouped cards' groups) whose threshold state is danger or warning, worst
    first; ``fine`` counts the success ones; cards without colour rules
    aren't rated."""
    metrics = {m.key: m for m in Metric.objects.filter(key__in=dashboard.metric_keys())}
    attention: list[dict[str, Any]] = []
    fine = 0
    for cell in dashboard.layout:
        if not isinstance(cell, dict) or cell.get("type") not in ("metric", "metric_group"):
            continue
        metric = cell_source(cell, metrics=metrics)
        if metric is None or not may_read(metric, request.user):
            continue
        when = cell_period(cell, period)
        name = str(cell_title(cell) or metric.name)
        if cell["type"] == "metric":
            result = evaluate(metric, request, period=when)
            states = [(name, result.state, result.display)]
        else:
            try:
                groups = _groups(metric, cell, request, when, other=False)
            except (FilterTreeError, ValueError):
                continue
            states = [(f"{name}: {g['label']}", g.get("state"), g["display"]) for g in groups]
        for label, state, display in states:
            if state in ("danger", "warning"):
                attention.append({"name": label, "state": state, "display": display})
            elif state == "success":
                fine += 1
    attention.sort(key=lambda a: a["state"] != "danger")
    return {
        "attention": attention,
        "fine": fine,
        "rated": len(attention) + fine,
        "when": period_heading(period).lower(),
    }


def board_embed(
    dashboard: Dashboard, request: HttpRequest, *, period: Optional[str] = None, lazy: bool = True
) -> dict[str, Any]:
    """*dashboard* laid out for embedding in any page: ``{dashboard, period,
    heading, refresh, cells: [{id, type, x, y, w, h, url, html}]}``, cells in
    reading order (top to bottom, left to right — how they stack on a phone).

    *period* defaults to the dashboard's own; ``""`` means all time. ``lazy`` cells carry ``url`` (the
    cell endpoint, which htmx loads); otherwise ``html`` is rendered now through
    :func:`render_cell` (no htmx needed — an email, a PDF, a test)."""
    period = (dashboard.default_period or None) if period is None else (period or None)
    cells = []
    from .components import widget_refused

    for cell in sorted(
        (c for c in dashboard.layout if isinstance(c, dict)), key=lambda c: (c.get("y", 0), c.get("x", 0))
    ):
        if dashboard.system_key and widget_refused(cell, request.user):
            continue  # as the page does (T5-9)
        url = reverse("dashboards_cell", kwargs={"slug": dashboard.slug, "cell_id": cell["id"]})
        html: SafeString | None = None
        if not lazy:
            html = mark_safe(render_cell(dashboard, cell, request, period))  # noqa: S308 — rendered by our templates
        cells.append(
            {
                "id": cell["id"],
                "type": cell.get("type"),
                "x": int(cell.get("x", 0)),
                "y": int(cell.get("y", 0)),
                "w": int(cell.get("w", 3)),
                "h": int(cell.get("h", 2)),
                "url": f"{url}?period={period or 'all'}",
                "html": html,
                "options": cell.get("options") or {},  # publish / listen: linked cards (cards.js)
            }
        )
    return {
        "dashboard": dashboard,
        "period": period,
        "heading": period_heading(period),
        "refresh": dashboard.refresh_seconds or 0,
        "cells": cells,
    }


def set_picture(dashboard: Dashboard, image: UploadedFile, alt: str = "") -> dict[str, Any]:
    """Give *dashboard* a new picture — the REST picture route and the MCP
    tool both land here. Returns ``{"ok", "cover_image", "cover_alt"}`` or
    ``{"error", "problems"}``; the caller has already checked ``can_edit``.
    The replaced file is deleted after the commit (``signals.py``)."""
    form = DashboardPictureForm(data={"cover_alt": alt}, files={"cover_image": image}, instance=dashboard)
    if not form.is_valid():
        return {"error": "the picture was not saved", "problems": form.errors.get_json_data()}
    form.save()
    return picture_payload(dashboard)


def clear_picture(dashboard: Dashboard) -> dict[str, Any]:
    dashboard.cover_image = ""  # type: ignore[assignment]
    dashboard.cover_alt = ""
    dashboard.save()
    return picture_payload(dashboard)


# -- sharing a personal dashboard --------------------------------------------


def share_payload(dashboard: Dashboard) -> dict[str, Any]:
    """Who a dashboard is shared with, as the share dialog and the
    ``dashboard_share`` tool report it."""
    people = list(dashboard.shared_with.order_by("username")) if dashboard.pk else []
    return {
        "ok": True,
        "everyone": bool(dashboard.shared_with_everyone),
        "people": [{"username": u.get_username(), "name": u.get_full_name() or u.get_username()} for u in people],
        "audience": dashboard.audience(),
    }


def set_sharing(
    dashboard: Dashboard,
    *,
    actor: Any,
    everyone: Optional[bool] = None,
    add: Any = (),
    remove: Any = (),
) -> dict[str, Any]:
    """Share a personal dashboard, or stop: *everyone* (everyone who can sign
    in), *add* / *remove* people (users, pks or usernames). The owner keeps
    editing it; the people added get a notification with the link. An
    ownerless dashboard is everyone's already, so there's nothing to set."""
    from django.contrib.auth import get_user_model

    if dashboard.owner_id is None:
        return {"error": "this dashboard is shared with everyone already (it has no owner)"}
    User = get_user_model()

    def people(raw: Any) -> list[Any]:
        found = []
        for item in raw or ():
            if isinstance(item, User):
                found.append(item)
                continue
            lookup = {"pk": item} if isinstance(item, int) or str(item).isdigit() else {"username": str(item)}
            user = User.objects.filter(is_active=True, **lookup).first()
            if user is not None:
                found.append(user)
        return [u for u in found if u.pk != dashboard.owner_id]

    if everyone is not None and bool(everyone) != dashboard.shared_with_everyone:
        dashboard.shared_with_everyone = bool(everyone)
        dashboard.save(update_fields=["shared_with_everyone", "updated_at"])
    added = [u for u in people(add) if not dashboard.shared_with.filter(pk=u.pk).exists()]
    if added:
        dashboard.shared_with.add(*added)
        _notify_shared(dashboard, added, actor)
    gone = people(remove)
    if gone:
        dashboard.shared_with.remove(*gone)
    out = {**share_payload(dashboard), "added": [u.get_username() for u in added]}
    # Shared "so she can look at it", a person may still read none of it: the
    # data is staff-only, or a metric is the owner's own. Say so now, rather
    # than leave the viewer to find dashes.
    blind = {u.get_username(): names for u in added if (names := unreadable_cards(dashboard, u))}
    if blind:
        out["cant_read"] = blind
        out["warning"] = "; ".join(
            f"{who} can't read {len(names)} of the cards ({', '.join(names)}): they show as restricted"
            for who, names in blind.items()
        )
    return out


def unreadable_cards(dashboard: Dashboard, user: Any) -> list[str]:
    """The titles of *dashboard*'s cards *user* won't see a number on: a
    dataset beyond their access (what ``evaluate`` marks restricted), or the
    owner's own hand-entered metric, whose entries only its owner reads."""
    names = []
    for cell in dashboard.layout or []:
        metric = cell_source(cell)
        if metric is None:
            continue
        if not may_read(metric, user):
            names.append(str(cell_title(cell) or metric.name))
    return names


def _notify_shared(dashboard: Dashboard, users: list[Any], actor: Any) -> None:
    """A bell for each person just given the dashboard, the first time only:
    removing and adding someone again sent the sender's text again, with no
    limit. Best-effort."""
    try:
        from apps.notifications.models import Notification
        from apps.notifications.services import notify

        told = set(
            Notification.objects.filter(
                kind="dashboards.shared", subject_key=f"dashboard:{dashboard.slug}", recipient__in=users
            ).values_list("recipient_id", flat=True)
        )
        users = [u for u in users if u.pk not in told]
        if not users:
            return

        who = actor.get_full_name() or actor.get_username() if actor is not None else "Someone"
        notify(
            users,
            title=f"{who} shared a dashboard with you: {dashboard.name}",
            message=dashboard.description or "Open it from Dashboards, under Shared with you.",
            url=dashboard.get_absolute_url(),
            kind="dashboards.shared",
            actor=actor,
            subject_key=f"dashboard:{dashboard.slug}",
        )
    except Exception:  # noqa: BLE001 — a bell is a courtesy, never a reason sharing fails
        logger.exception("dashboards: share notification failed for %s", dashboard.slug)


def picture_payload(dashboard: Dashboard) -> dict[str, Any]:
    return {
        "ok": True,
        "cover_image": dashboard.cover_image.url if dashboard.cover_image else None,
        "cover_alt": dashboard.cover_alt,
    }


# -- system dashboards: a page built on a dashboard row ---------------------------------


def system_dashboard(key: str, *, name: str, description: str = "") -> Dashboard:
    """The shared dashboard a page is built on (``Dashboard.system_key``),
    created on first use and kept in step with the published widgets.

    ``/smallstack/`` is ``system_dashboard(ADMIN_HOME_KEY, …)``; a downstream
    page can pin its own key the same way and get the editable grid, the
    period bar and the widget cards for free."""
    from django.db import IntegrityError, transaction
    from django.utils.text import slugify

    dashboard = Dashboard.objects.filter(system_key=key).first()
    if dashboard is None:
        slug = base = slugify(key)[:70] or "system"
        n = 2
        while Dashboard.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        try:
            with transaction.atomic():
                dashboard = Dashboard(name=name, slug=slug, description=description, system_key=key)
                dashboard.save()
        except IntegrityError:  # created by a concurrent first request
            dashboard = Dashboard.objects.get(system_key=key)
    sync_widgets(dashboard)
    return dashboard


def publishable_widgets() -> list[tuple[str, Any]]:
    """``[(key, widget)]`` for every widget an app publishes to dashboards
    (``on_dashboard=True``), in the widgets' own ``order``."""
    from .components import available_widgets

    found = [(key, widget) for key, widget, _info in available_widgets() if getattr(widget, "on_dashboard", True)]
    return sorted(found, key=lambda kw: getattr(kw[1], "order", 50))


def sync_widgets(dashboard: Dashboard) -> list[str]:
    """Place each newly published widget on *dashboard*; drop cards whose
    widget is gone. Returns the keys added.

    A widget is placed once: its key goes into ``offered_widgets``, so a card
    someone removes stays removed (Add card → Widget brings it back). A card
    whose widget is no longer registered — its app was disabled — leaves the
    layout and ``offered_widgets`` both, so it returns if the app does. New
    cards fill rows left to right below the existing ones, sized by the
    widget's ``span`` (3 columns each, the old four-across grid)."""
    from django.db import transaction

    from .components import available_widgets

    registered = {key for key, _w, _i in available_widgets()}
    if not _widgets_out_of_step(dashboard, registered):
        return []  # the common case: one read, no lock
    with transaction.atomic():
        board = Dashboard.objects.select_for_update().get(pk=dashboard.pk)
        offered = [k for k in board.offered_widgets if isinstance(k, str) and k in registered]
        layout = [
            c
            for c in board.layout
            if not (c.get("type") == "widget" and (c.get("options") or {}).get("widget") not in registered)
        ]
        placed = {(c.get("options") or {}).get("widget") for c in layout if c.get("type") == "widget"}
        # A widget someone already put on the board by hand counts as offered:
        # mark it, don't place a second copy (T5-3).
        offered += [k for k, _w in publishable_widgets() if k in placed and k not in offered]
        fresh = [(k, w) for k, w in publishable_widgets() if k not in offered]
        if not fresh and layout == board.layout and offered == board.offered_widgets:
            return []
        bottom = max((int(c.get("y") or 0) + int(c.get("h") or 1) for c in layout), default=0)
        x, y, row_h = 0, bottom, 0
        for key, widget in fresh:
            w = min(12, 3 * max(1, int(getattr(widget, "span", 1) or 1)))
            if x + w > 12:
                x, y, row_h = 0, y + row_h, 0
            layout.append({"type": "widget", "x": x, "y": y, "w": w, "h": 2, "options": {"widget": key}})
            x, row_h = x + w, max(row_h, 2)
            offered.append(key)
        board.layout = layout
        board.offered_widgets = offered
        board.save()
    dashboard.refresh_from_db()
    return [k for k, _w in fresh]


def _widgets_out_of_step(dashboard: Dashboard, registered: set[str]) -> bool:
    offered = set(dashboard.offered_widgets)
    if any(k not in offered for k, _w in publishable_widgets()):
        return True
    if any(k not in registered for k in offered):
        return True
    return any(
        c.get("type") == "widget" and (c.get("options") or {}).get("widget") not in registered for c in dashboard.layout
    )


# -- the cards on a dashboard, as a table (the settings page) ---------------------------

#: What the cards table sorts by. ``value`` evaluates every card, only when asked.
CARD_SORTS = ("name", "design", "metric", "size", "value")


def cell_value(dashboard: Dashboard, cell: dict[str, Any], request: HttpRequest) -> dict[str, Any]:
    """One card's headline as a short value, at the dashboard's own period:
    ``{display, unit, state, number, note, problem, restricted}``. A metric
    card's number (a grouped card's total), a widget's headline, a goals
    card's "6 of 8 on target"; a note or an app's card with no one number has
    neither. Never raises, and never shows a user what they may not read."""
    from .components import available_widgets, card_style, styled_value, widget_number
    from .metrics import _is_number

    out: dict[str, Any] = {
        "display": "",
        "unit": "",
        "state": None,
        "number": None,
        "note": "",
        "problem": "",
        "restricted": False,
    }
    ct = get_component_type(str(cell.get("type", "")))
    user = request.user
    if ct is None:
        out["problem"] = "Unknown card type"
        return out
    if ct.visible_to is not None and not ct.visible_to(user):
        out["restricted"] = True
        return out
    try:
        if ct.needs_metric:
            metric = cell_source(cell)
            if metric is None:
                out["problem"] = "Its metric no longer exists" if cell.get("metric") else "It has no source"
            elif not may_read(metric, user):
                out["restricted"] = True
            else:
                result = evaluate(metric, request, period=cell_period(cell, dashboard.default_period or None))
                if not result.ok:
                    out["problem"] = result.error or "Can't evaluate"
                else:
                    shown = styled_value(result.value, metric, card_style(cell), result.state)
                    out.update(display=shown["display"], unit=shown["unit"], state=shown["state"])
                    out["number"] = float(result.value) if _is_number(result.value) else None
                    out["note"] = "total" if ct.key == "metric_group" else ""
        elif ct.key == "goals":
            from .goals import evaluate_goals
            from .models import GoalList

            goal_list = GoalList.objects.filter(slug=(cell.get("options") or {}).get("goal_list") or "").first()
            if goal_list is None:
                out["problem"] = "Its goal list no longer exists"
            elif not goal_list.can_view(user):
                out["restricted"] = True
            else:
                summary = evaluate_goals(
                    goal_list, request, period=cell_period(cell, dashboard.default_period or None), compare=False
                )["summary"]
                out["display"], out["number"] = summary["headline"], summary["pct"]
        elif ct.key == "widget":
            key = (cell.get("options") or {}).get("widget")
            found = next(((w, i) for k, w, i in available_widgets() if k == key), None)
            if found is None:
                out["problem"] = "This widget is no longer published"
            else:
                widget, info = found
                from apps.smallstack.displays import widget_data

                data = widget_data(widget, user, info.model_class if info is not None else None)
                out["display"], out["number"] = str(data.get("headline") or ""), widget_number(data)
    except Exception:  # noqa: BLE001 — one card's failure must not take the table down
        logger.exception("dashboard %s card %s: value failed", dashboard.slug, cell.get("id"))
        out["problem"] = "Can't evaluate"
    return out


def board_cards(dashboard: Dashboard, request: HttpRequest, order: str = "") -> dict[str, Any]:
    """The cards as table rows, in reading order unless *order* says otherwise:
    ``{rows: [{id, name, design, icon, metric, metric_url, size, value_url,
    value}], order, links, heading}``. *order* is one of :data:`CARD_SORTS`,
    ``-`` to flip. ``value`` is filled in only when sorting by it; otherwise
    each row loads its own from ``value_url``. Sorting only changes this
    table: a card's place on the dashboard comes from its grid position."""
    cells = sorted((c for c in dashboard.layout if isinstance(c, dict)), key=lambda c: (c.get("y", 0), c.get("x", 0)))
    keys = {c["metric"] for c in cells if isinstance(c.get("metric"), str)}
    metrics = {m.key: m for m in Metric.objects.filter(key__in=keys)}
    rows: list[dict[str, Any]] = []
    for cell in cells:
        ct = get_component_type(str(cell.get("type", "")))
        metric = metrics.get(str(cell.get("metric") or ""))
        name = cell_title(cell) or (metric.name if metric else "") or (ct.label if ct else str(cell.get("type")))
        own = inline_source(cell) if metric is None else None
        rows.append(
            {
                "id": cell.get("id"),
                "cell": cell,
                "name": name,
                "design": str(ct.label) if ct else str(cell.get("type")),
                "icon": ct.icon if ct else "",
                "metric": metric.name if metric else "",
                "metric_key": str(cell.get("metric") or ""),
                "metric_url": metric.get_absolute_url() if metric else "",
                # A card with a source of its own: the dataset it filters, in a word.
                "dataset": own.dataset if own is not None else "",
                "needs_metric": bool(ct and ct.needs_metric),
                "size": f"{cell.get('w', 1)} × {cell.get('h', 1)}",
                "area": int(cell.get("w", 1)) * int(cell.get("h", 1)),
                "value_url": reverse(
                    "dashboards_board_card_value", kwargs={"slug": dashboard.slug, "cell_id": cell.get("id")}
                ),
                "value": None,
            }
        )
    raw = str(order or "").strip()
    valid = raw if raw.lstrip("-") in CARD_SORTS else ""
    desc, key = valid.startswith("-"), valid.lstrip("-")
    if key == "value":
        for row in rows:
            row["value"] = cell_value(dashboard, row["cell"], request)
        have = [r for r in rows if r["value"]["number"] is not None]
        rest = [r for r in rows if r["value"]["number"] is None]
        have.sort(key=lambda r: r["value"]["number"], reverse=desc)
        rows = have + rest
    elif key == "size":
        rows.sort(key=lambda r: r["area"], reverse=desc)
    elif key:
        rows.sort(key=lambda r: str(r[key]).lower(), reverse=desc)
    base = reverse("dashboards_board_cards", kwargs={"slug": dashboard.slug})
    links = {}
    for sort_key in CARD_SORTS:
        if valid == sort_key:
            nxt, aria = f"-{sort_key}", "ascending"
        elif valid == f"-{sort_key}":
            nxt, aria = sort_key, "descending"
        else:
            nxt, aria = (f"-{sort_key}" if sort_key in ("size", "value") else sort_key), "none"
        links[sort_key] = {"url": f"{base}?order={nxt}", "aria_sort": aria}
    return {
        "rows": rows,
        "order": valid,
        "links": links,
        "base_url": base,
        "heading": period_heading(dashboard.default_period or None).lower(),
    }


# -- a card of its own: unlinking a placed saved card, copying a card's metric --------

#: What a copy of a metric carries over: everything that defines the number, and
#: the labels. Not the key (made from the new name), the owner or the dates.
METRIC_COPIED = (
    "description",
    "source",
    "dataset",
    "numerator",
    "denominator",
    "filter_tree",
    "agg",
    "measure",
    "period_field",
    "format",
    "unit",
    "thresholds",
    "tags",
)


def placement_counts(keys: set[str]) -> dict[str, int]:
    """How many dashboards show each saved card in *keys*. A dashboard that
    places one twice counts once: the question is "who else changes with it"."""
    counts: dict[str, int] = {}
    if not keys:
        return counts
    for layout in Dashboard.objects.values_list("layout", flat=True):
        placed = {str(c["component"]) for c in layout or [] if isinstance(c, dict) and c.get("component")}
        for key in placed & keys:
            counts[key] = counts.get(key, 0) + 1
    return counts


def copyable_metric(key: Any, user: Any) -> Optional[Metric]:
    """The metric a card could be given its own copy of: one *user* may see,
    and not one entered by hand, whose values are typed against that metric
    and wouldn't come along."""
    metric = Metric.objects.filter(key=key).first() if isinstance(key, str) and key else None
    if metric is None or metric.is_manual or not metric.can_view(user):
        return None
    return metric


def make_card_unique(dashboard: Dashboard, cell_id: str, user: Any, *, copy_metric: bool = False) -> dict[str, str]:
    """Make one card this dashboard's own, where it sits.

    A cell that places a saved card stops following it: it keeps the design it
    was showing (the cell already carries a copy) under the card's name, and
    the saved card and every other dashboard are left as they were. With
    *copy_metric* the card's metric is copied too (``"<name> (<dashboard>)"``,
    owned like the dashboard) and the card draws the copy, so its filter can
    change here alone. That part also suits a card that was never a saved one,
    on a duplicated dashboard still sharing its metrics with the original.

    Its place, size and options don't change. Returns ``{"metric": key}`` (the
    new metric's key, or ""). Raises ``LookupError`` for a card that isn't
    there, and ``ValidationError`` when the layout or the metric won't save;
    nothing is kept then."""
    from django.db import transaction

    cell = dashboard.cell(cell_id)
    if cell is None:
        raise LookupError(cell_id)
    fresh = copy.deepcopy(cell)
    if fresh.pop("component", None):
        name = fresh.pop("name", "")
        if name and not fresh.get("title"):
            fresh["title"] = name
    created: Optional[Metric] = None
    with transaction.atomic():
        original = copyable_metric(fresh.get("metric"), user) if copy_metric else None
        if original is not None:
            name = f"{original.name} ({dashboard.name})"[:120]
            created = Metric(
                key=metric_key_from_name(name),
                name=name,
                owner_id=dashboard.owner_id,
                created_by=user,
                **{field: copy.deepcopy(getattr(original, field)) for field in METRIC_COPIED},
            )
            created.save()
            fresh["metric"] = created.key
        dashboard.layout = [fresh if c.get("id") == cell_id else c for c in dashboard.layout]
        dashboard.save()
    return {"metric": created.key if created is not None else ""}


def visible_layout(dashboard: Dashboard, user: Any) -> list[dict[str, Any]]:
    """The layout as ``user`` sees it: on a system board, without the widget
    cards their ``visible_to`` refuses (T5-9)."""
    from .components import widget_refused

    cells = [c for c in dashboard.layout if isinstance(c, dict)]
    if not dashboard.system_key:
        return cells
    return [c for c in cells if not widget_refused(c, user)]


def keep_hidden_cells(dashboard: Dashboard, posted: list[Any], user: Any) -> list[Any]:
    """An editor who can't see some cards of a system board saves the layout
    they saw: keep the cards hidden from them as stored, and move any whose
    slot the new layout now covers below everything (G3-1). An editor who sees
    every card gets exactly what they posted."""
    from .components import widget_refused

    if not dashboard.system_key:
        return posted
    hidden = [c for c in dashboard.layout if isinstance(c, dict) and widget_refused(c, user)]
    if not hidden:
        return posted
    hidden_ids = {c.get("id") for c in hidden}
    cells = [c for c in posted if not (isinstance(c, dict) and c.get("id") in hidden_ids)]

    def box(c: Any) -> tuple[int, int, int, int]:
        return int(c.get("x") or 0), int(c.get("y") or 0), int(c.get("w") or 1), int(c.get("h") or 1)

    def overlaps(a: Any, b: Any) -> bool:
        ax, ay, aw, ah = box(a)
        bx, by, bw, bh = box(b)
        return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah

    # The editor's grid had no slot for the hidden cards, so the cards below
    # them floated up. Put the hidden ones back where they were and push the
    # visible cards they now overlap down again (G5-2), column by column, as
    # the grid would have; only if that still collides is a hidden card moved
    # to the bottom.
    posted_cells = [dict(c) for c in cells if isinstance(c, dict)]
    for cell in sorted(hidden, key=lambda c: box(c)[1]):
        hx, hy, hw, hh = box(cell)
        for c in posted_cells:
            cx, cy, cw, _ch = box(c)
            if cx < hx + hw and hx < cx + cw and cy + _ch > hy:
                c["y"] = cy + hh
    placed: list[dict[str, Any]] = list(posted_cells)
    for cell in hidden:
        if any(overlaps(cell, c) for c in placed):
            bottom = max((box(c)[1] + box(c)[3] for c in placed), default=0)
            cell = {**cell, "x": 0, "y": bottom}
        placed.append(cell)
    if any(overlaps(a_, b_) for i, a_ in enumerate(placed) for b_ in placed[i + 1:]):
        # The push created a collision between visible cards: fall back to
        # the posted layout with the hidden cards below it.
        bottom = max((box(c)[1] + box(c)[3] for c in cells if isinstance(c, dict)), default=0)
        return list(cells) + [{**c, "x": 0, "y": bottom + 2 * i} for i, c in enumerate(hidden)]
    return placed
