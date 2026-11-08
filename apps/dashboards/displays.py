"""List displays for the dashboards CRUD pages."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from django.urls import reverse

from apps.smallstack.displays import ListAccessory, ListDisplay, paginate_queryset

_HOW = {
    "count": "Counts rows",
    "distinct": "Counts distinct {measure}",
    "sum": "Totals {measure}",
    "avg": "Averages {measure}",
    "min": "Lowest {measure}",
    "max": "Highest {measure}",
}


#: Each owned kind: the word for one, for several, and the list it's in.
_KINDS = {
    "Dashboard": ("dashboard", "dashboards", "dashboards/boards-list"),
    "Playlist": ("playlist", "playlists", "dashboards/playlists-list"),
    "Component": ("card", "cards", "dashboards/components-list"),
    "GoalList": ("goal list", "goal lists", "dashboards/goals-list"),
    "Metric": ("metric", "metrics", "dashboards/metrics-list"),
    "Report": ("report", "reports", "dashboards/reports-list"),
}


def archived_links(user: Any, *models: Any) -> list[dict[str, str]]:
    """What an overview says has been archived: ``[{text, url}]``, "2 metrics"
    linking to that list's archived rows, for each kind with any (none: [])."""
    out = []
    for model in models:
        count = model.objects.visible_to(user).archived().count()
        if count:
            one, many, url_name = _KINDS[model.__name__]
            out.append({"text": f"{count} {one if count == 1 else many}", "url": f"{reverse(url_name)}?archived=1"})
    return out


class TagBar(ListAccessory):
    """Above a list: the tags its rows carry, each narrowing the list to it
    (``?tag=``, read by ``_OwnedCRUD.get_list_queryset``). Counted over every
    row the person may see, whatever the list is narrowed to, so the other
    tags stay one click away. It's also the way between the list and what's
    been archived from it (``?archived=1``): "Show archived (N)" when there's
    any, "Back to the list" while showing them."""

    template_name = "dashboards/partials/tag_filter.html"

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from .models import tag_cloud

        every = crud_config.model.objects.visible_to(getattr(request, "user", None))
        showing_archived = request.GET.get("archived") == "1"
        rows = every.archived() if showing_archived else every.active()
        tag = request.GET.get("tag", "").strip()
        return {
            "tags": tag_cloud(rows, current=tag),
            "tag": tag,
            # How to add a first tag belongs on the list, not among what's been put away.
            "tag_hint": not showing_archived and rows.exists(),
            "showing_archived": showing_archived,
            "list_archived_count": 0 if showing_archived else every.archived().count(),
        }


class MetricLibraryDisplay(ListDisplay):
    """The metric library: each metric with its filter in words, where its data
    comes from, where it's used, and what it says right now (evaluated live
    for the page being shown, never the whole table)."""

    name = "library"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
        '<path d="M4 6h16v2H4zm0 5h10v2H4zm0 5h16v2H4zm14-6h2v4h-2z"/></svg>'
    )
    template_name = "dashboards/displays/metric_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.datasets.registry import get_def
        from apps.smallstack.crud import Action

        from .comparison import compare_with_previous
        from .metrics import evaluate
        from .models import Dashboard, Report
        from .periods import SHORT_PERIODS, period_heading, plain_reading, requested_period

        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        user = getattr(request, "user", None)
        base = crud_config._get_url_base()

        # The same period links as the dashboards index; other query params
        # (search, ordering, display) ride along so a period never resets them.
        period = requested_period(request)
        params = request.GET.copy()
        params.pop("page", None)
        period_links = []
        for key, label in SHORT_PERIODS:
            params["period"] = key
            period_links.append(
                {"key": key, "label": label, "url": f"?{params.urlencode()}", "current": key == (period or "all")}
            )
        heading = period_heading(period).lower()

        on_boards: dict[str, list[str]] = {}
        in_reports: dict[str, list[str]] = {}
        for d in Dashboard.objects.visible_to(user).active():
            for key in d.metric_keys():
                on_boards.setdefault(key, []).append(d.name)
        for r in Report.objects.visible_to(user).active():
            for key in set(r.metric_keys()):
                in_reports.setdefault(key, []).append(r.name)

        rows = []
        for m in items:
            dfn = get_def(m.dataset)
            measure = m.measure_label
            can_edit = m.can_edit(user)
            rows.append(
                {
                    "obj": m,
                    "url": m.get_absolute_url(),
                    "reading": plain_reading(m.filter_summary),
                    "source": m.source_label if (dfn is not None or m.is_rate) else f"{m.dataset} (unavailable)",
                    "source_missing": dfn is None and not m.is_rate,
                    "how": "One metric divided by another"
                    if m.is_rate
                    else _HOW.get(m.agg, "{measure}").format(measure=measure or "values"),
                    "period_aware": bool(m.period_field),
                    "used": _usage(on_boards.get(m.key, []), in_reports.get(m.key, [])),
                    "result": (result := evaluate(m, request, period=period)),
                    "comparison": compare_with_previous(m, request, period, result) if period else None,
                    "all_time": bool(period) and not m.period_field,
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": m.pk})
                    if can_edit and Action.UPDATE in crud_config.actions
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": m.pk})
                    if can_edit and Action.DELETE in crud_config.actions
                    else "",
                }
            )
        return {
            "rows": rows,
            "object_list": items,
            "period_links": period_links,
            "period_heading": heading,
            **page,
        }


def _usage(boards: list[str], reports: list[str]) -> dict[str, str]:
    """``{text, names}``: "1 dashboard, 2 reports" and the names for a tooltip."""
    parts = []
    if boards:
        parts.append(f"{len(boards)} dashboard{'s' if len(boards) != 1 else ''}")
    if reports:
        parts.append(f"{len(reports)} report{'s' if len(reports) != 1 else ''}")
    return {"text": ", ".join(parts), "names": ", ".join(boards + reports)}


class ReportLibraryDisplay(ListDisplay):
    """Reports as sentences — what each compares, across which periods — with
    a warning when a row points at a metric that no longer exists, and each
    one's movement (rows up / down between its first two columns), loaded per
    row as it scrolls into view. No values: a report is metrics × periods, too
    heavy to evaluate for a list — except when the list is sorted by movement
    (``?ordering=movement``, most fallen first; ``-movement``, most risen),
    which evaluates every report it shows, then pages the sorted result."""

    name = "library"
    icon = MetricLibraryDisplay.icon
    template_name = "dashboards/displays/report_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        from .models import Metric
        from .periods import period_heading
        from .reports import sort_by_movement

        ordering = request.GET.get("ordering", "").strip()
        movements: dict[int, Any] = {}
        if ordering.lstrip("-") == "movement":
            # Not a column: every report is evaluated so the sort spans them all.
            ranked = sort_by_movement(list(queryset), request, desc=ordering.startswith("-"))
            movements = {r.pk: m for r, m in ranked}
            queryset = [r for r, _m in ranked]
        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        user = getattr(request, "user", None)
        base = crud_config._get_url_base()
        keys = {k for r in items for k in r.metric_keys()}
        names = dict(Metric.objects.filter(key__in=keys).values_list("key", "name"))
        rows = []
        for r in items:
            rkeys = r.metric_keys()
            can_edit = r.can_edit(user)
            rows.append(
                {
                    "obj": r,
                    "url": r.get_absolute_url(),
                    "digest_url": reverse("dashboards_report_digest", kwargs={"slug": r.slug}),
                    "movement": movements.get(r.pk),
                    "sorted_by_movement": bool(movements),
                    "columns": [period_heading(p) for p in r.periods] or ["All time"],
                    "metric_names": [names[k] for k in rkeys if k in names],
                    "missing": sum(1 for k in rkeys if k not in names),
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": r.pk})
                    if can_edit and Action.UPDATE in crud_config.actions
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": r.pk})
                    if can_edit and Action.DELETE in crud_config.actions
                    else "",
                }
            )
        return {"rows": rows, "object_list": items, **page}


class DashboardLibraryDisplay(ListDisplay):
    """Dashboards recognised by their shape: a miniature of each layout, what
    it holds, how it opens, and whether any of its cards have broken."""

    name = "library"
    icon = MetricLibraryDisplay.icon
    template_name = "dashboards/displays/dashboard_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        from .components import get_component_type
        from .models import Metric
        from .periods import period_heading

        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        user = getattr(request, "user", None)
        base = crud_config._get_url_base()
        keys = {k for d in items for k in d.metric_keys()}
        known = set(Metric.objects.filter(key__in=keys).values_list("key", flat=True))
        rows = []
        for d in items:
            cells = [c for c in d.layout if isinstance(c, dict)]
            kinds: dict[str, int] = {}
            broken = 0
            for c in cells:
                ct = get_component_type(str(c.get("type", "")))
                if ct is None or (ct.needs_metric and not c.get("dataset") and c.get("metric") not in known):
                    broken += 1
                label = "note" if c.get("type") == "text" else (ct.label if ct else "unknown card").lower()
                kinds[label] = kinds.get(label, 0) + 1
            kinds = dict(sorted(kinds.items(), key=lambda kv: kv[0] == "note"))  # notes last
            can_edit = d.can_edit(user)
            rows.append(
                {
                    "obj": d,
                    "url": d.get_absolute_url(),
                    "digest_url": reverse("dashboards_digest", kwargs={"slug": d.slug}),
                    "count": len(cells),
                    "kinds": ", ".join(f"{n} {k}{'s' if n != 1 else ''}" for k, n in kinds.items()),
                    "opens": period_heading(d.default_period).lower() if d.default_period else "all time",
                    "broken": broken,
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": d.pk})
                    if can_edit and Action.UPDATE in crud_config.actions
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": d.pk})
                    if Action.DELETE in crud_config.actions and crud_config.can_delete(d, request)
                    else "",
                }
            )
        return {"rows": rows, "object_list": items, **page}


class PlaylistLibraryDisplay(ListDisplay):
    """Playlists as a strip of their dashboards' covers, how they play, and a
    Play button — the list is where you start one."""

    name = "library"
    icon = MetricLibraryDisplay.icon
    template_name = "dashboards/displays/playlist_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        from .playlists import playlist_slides

        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        user = getattr(request, "user", None)
        base = crud_config._get_url_base()
        rows = []
        for p in items:
            slides = playlist_slides(p, user)
            rows.append(
                {
                    "obj": p,
                    "url": p.get_absolute_url(),
                    "slides": slides,
                    "strip": slides[:4],
                    "more": max(len(slides) - 4, 0),
                    "minutes": round(sum(s["seconds"] for s in slides) / 60, 1),
                    "hidden": len(p.items) - len(slides),
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": p.pk})
                    if Action.UPDATE in crud_config.actions and crud_config.can_update(p, request)
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": p.pk})
                    if Action.DELETE in crud_config.actions and crud_config.can_delete(p, request)
                    else "",
                }
            )
        return {"rows": rows, "object_list": items, **page}


def _dataset_label(key: str) -> str:
    from apps.datasets.registry import get_def

    dfn = get_def(key)
    return str(getattr(dfn, "label", "") or key) if dfn is not None else key


class ComponentLibraryDisplay(ListDisplay):
    """Saved cards: what each draws (type and metric), and how many
    dashboards show it — an edit reaches all of them."""

    name = "library"
    icon = MetricLibraryDisplay.icon
    template_name = "dashboards/displays/component_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        from .components import get_component_type
        from .models import Dashboard, Metric

        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        base = crud_config._get_url_base()
        keys = {c.key for c in items}
        used: dict[str, int] = {}
        for layout in Dashboard.objects.values_list("layout", flat=True):
            for cell in layout or []:
                if isinstance(cell, dict) and cell.get("component") in keys:
                    used[cell["component"]] = used.get(cell["component"], 0) + 1
        names = dict(Metric.objects.filter(key__in={c.metric for c in items if c.metric}).values_list("key", "name"))
        goal_add = reverse("dashboards_goal_add")
        rows = []
        for c in items:
            ct = get_component_type(c.type)
            rows.append(
                {
                    "obj": c,
                    "type_label": ct.label if ct else f"{c.type} (not registered)",
                    "icon": ct.icon if ct else "",
                    "group": ct.group if ct else "",
                    "preview_url": reverse("dashboards_component_preview", kwargs={"pk": c.pk}),
                    "metric_name": names.get(c.metric, c.metric),
                    "source_name": _dataset_label(c.dataset) if c.dataset else "",
                    "used": used.get(c.key, 0),
                    "goal_url": f"{goal_add}?component={c.key}"
                    if ct is not None and ct.single_value and c.metric  # a goal judges a metric
                    else "",
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": c.pk})
                    if Action.UPDATE in crud_config.actions and crud_config.can_update(c, request)
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": c.pk})
                    if Action.DELETE in crud_config.actions and crud_config.can_delete(c, request)
                    else "",
                }
            )
        # Narrowed to a dashboard (?dashboard=): say so above the cards, with the
        # way to the dashboard itself — this is where its cards are edited.
        slug = request.GET.get("dashboard", "")
        board = Dashboard.objects.visible_to(getattr(request, "user", None)).filter(slug=slug).first() if slug else None
        paginator = page.get("paginator")
        scope = (
            {"name": board.name, "url": board.get_absolute_url(), "count": paginator.count if paginator else len(items)}
            if board is not None
            else None
        )
        # Card types' own files are in the page's head (component_list.html, {% component_media %}),
        # not here: this block is swapped in place, and a script written here would run again.
        return {"rows": rows, "object_list": items, "scope": scope, **page}


class ComponentCardsDisplay(ComponentLibraryDisplay):
    """Saved cards as a gallery: each one drawn for real, loading as it scrolls into view."""

    name = "cards"
    icon = (
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">'
        '<path d="M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z"/></svg>'
    )
    template_name = "dashboards/displays/component_cards.html"


class GoalListLibraryDisplay(ListDisplay):
    """Goal lists as a table: what each holds, how it's doing right now (a
    summary line loaded per row, so the list costs nothing up front), the
    period it judges over, and Present / Settings / Delete."""

    name = "library"
    icon = MetricLibraryDisplay.icon
    template_name = "dashboards/displays/goal_library.html"
    supports_bulk = False

    def get_context(self, queryset: Any, crud_config: Any, request: HttpRequest) -> dict[str, Any]:
        from apps.smallstack.crud import Action

        from .periods import period_heading

        page = paginate_queryset(queryset, crud_config.page_size_for(request), request)
        items = list(page.pop("object_list", queryset))
        base = crud_config._get_url_base()
        rows = []
        for g in items:
            sections = [s for s in g.sections if isinstance(s, dict)]
            titles = [s.get("title") for s in sections if s.get("title")]
            rows.append(
                {
                    "obj": g,
                    "url": g.get_absolute_url(),
                    "count": len(g.goals()),
                    "sections": len(sections),
                    "titles": titles,
                    "judged": period_heading(g.default_period or None),
                    "digest_url": reverse("dashboards_goals_digest", kwargs={"slug": g.slug}),
                    "weeks_url": reverse("dashboards_goal_weeks", kwargs={"slug": g.slug}),
                    "edit_url": reverse(f"{base}-update", kwargs={"pk": g.pk})
                    if Action.UPDATE in crud_config.actions and crud_config.can_update(g, request)
                    else "",
                    "delete_url": reverse(f"{base}-delete", kwargs={"pk": g.pk})
                    if Action.DELETE in crud_config.actions and crud_config.can_delete(g, request)
                    else "",
                }
            )
        return {"rows": rows, "object_list": items, **page}
