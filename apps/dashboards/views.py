"""Dashboards, metrics and reports — the SmallStack admin's pages over them.

These views are one consumer of the dashboards building blocks, built the way
a downstream app would build its own UI: every number, comparison and digest
comes from a service module, never from here.

==================  ==============================================================
``metrics``         evaluate a metric; the rows behind it; the metric in words
``comparison``      this period against the one before
``reports``         the report matrix, its presentation, CSV, movement
``boards``          render a dashboard cell; evaluate a board; what needs attention
``previews``        dry runs of an unsaved metric or report
``periods``         period vocabulary and wording
``components``      the card-type registry
==================  ==============================================================

Page shape (all under ``/smallstack/dashboards/``):

- ``/``                         the Dashboards overview — dashboards, playlists, saved cards
- ``/smallstack/goals/``        the Goals overview — goal lists, metrics (live values), reports
- ``d/<slug>/``                 a dashboard: a gridstack grid of lazily-loaded cells
- ``d/<slug>/cells/<id>/``      one cell's HTML (htmx ``load`` + optional ``every Ns``)
- ``d/<slug>/layout/``          POST the whole layout back (edit mode's Save)
- ``d/<slug>/digest/``          the "needs attention" line for the dashboards list
- ``d/<slug>/cards/``           the settings page's cards table (``?order=``)
- ``d/<slug>/cards/<id>/value/`` one card's value in that table
- ``m/<key>/``                  a metric: its number, filter, rows and where it's used
- ``m/<key>/rows/``             the drill-down fragment behind a card (the stat modal)
- ``metrics/preview-rows/``     the same fragment for an UNSAVED metric (the builder)
- ``r/<slug>/``                 a report (``?format=csv`` for the file)
- ``r/<slug>/digest/``          a report's movement for the reports list
- ``g/<slug>/``                 a goal list — the meeting view (``?present=1`` without the chrome)
- ``g/<slug>/digest/``          a goal list's "7 of 9 on target" line for lists
- ``goals/add/``                the "Add to goals" dialog (``?metric=`` or ``?component=``)
- ``metrics/``, ``boards/``, ``reports/``  the CRUDViews — HTML + REST + MCP from one class

Access is the models' ``can_view`` / ``can_edit`` everywhere; a card's number
additionally needs the metric's dataset to admit the viewer
(``DatasetDef.access``), so a shared dashboard never leaks a staff dataset.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import pluralize
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DeleteView, TemplateView

from apps.datasets.core import SafeCsvWriter, get_dataset
from apps.datasets.dateranges import RELATIVE_PERIODS
from apps.datasets.filter_tree import FilterTreeError, describe_filter_tree
from apps.datasets.registry import all_defs
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import TableDisplay
from apps.smallstack.pagination import PAGE_SIZE_CHOICES, page_size_from, paginate_queryset

from .boards import (
    METRIC_COPIED,
    board_attention,
    board_cards,
    cell_value,
    keep_hidden_cells,
    make_card_unique,
    placement_counts,
    render_cell,
    set_sharing,
    share_payload,
    system_dashboard,
    visible_layout,
)
from .comparison import compare_with_previous
from .components import (
    SOURCE_KEYS,
    available_widgets,
    cell_source,
    component_types,
    describe_types,
    get_component_type,
    is_inline,
    widget_refused,
)
from .datasets import visible_entries
from .displays import (
    ComponentCardsDisplay,
    ComponentLibraryDisplay,
    DashboardLibraryDisplay,
    GoalListLibraryDisplay,
    MetricLibraryDisplay,
    PlaylistLibraryDisplay,
    ReportLibraryDisplay,
    TagBar,
    archived_links,
)
from .entries import delete_entry, parse_entry, record_entry
from .forms import (
    AddGoalForm,
    ComponentForm,
    DashboardForm,
    GoalListForm,
    MetricForm,
    PlaylistForm,
    ReportForm,
    readable_datasets,
)
from .goals import add_goal, evaluate_goals, goal_order, goal_sort_links, sort_sections, suggest_target, summarize
from .metrics import (
    RATE_NO_ROWS,
    drill_csv,
    drill_rows,
    evaluate,
    format_value,
    may_read,
    metric_sentence,
    rate_parts,
    requested_drilldown,
    threshold_legend,
)
from .models import (
    ADMIN_HOME_KEY,
    SNAPSHOT_CADENCES,
    SOURCE_DATASET,
    Component,
    Dashboard,
    GoalList,
    Metric,
    OwnedModel,
    Playlist,
    Report,
    free_slug,
    metric_usage,
    tag_cloud,
)
from .periods import (
    QUICK_PERIODS,
    SHORT_PERIODS,
    join_words,
    period_choices,
    period_heading,
    period_phrase,
    plain_reading,
    requested_period,
)
from .playlists import player_context, playlist_slides, slide_embed
from .previews import unsaved_metric
from .reports import (
    present_report,
    report_matrix,
    report_movement,
    report_order,
    report_sort_links,
    sort_report,
    write_report_csv,
)


def visible_or_404(qs: QuerySet, request: HttpRequest, **lookup: Any) -> Any:
    obj = get_object_or_404(qs, **lookup)
    if not obj.can_view(request.user):
        raise Http404
    return obj


def period_nav(period: Optional[str]) -> dict[str, Any]:
    """The period bar's context: one-click links, the rest in a "More" select."""
    quick = dict(QUICK_PERIODS)
    return {
        "quick_periods": [{"key": k, "label": lbl, "current": k == (period or "all")} for k, lbl in QUICK_PERIODS],
        "more_periods": [(k, period_heading(k)) for k, _lbl in RELATIVE_PERIODS if k not in quick],
        "period_more_current": bool(period) and period not in quick,
    }


# -- pages --------------------------------------------------------------------------


class DashboardIndexView(LoginRequiredMixin, TemplateView):
    """The Dashboards overview: a few dashboards (as cards or a denser list,
    ``?boards=list``), playlists and saved cards, most recently changed first,
    with a link to each full (paged) list once there are more. Counts come from
    ``count()``; by default nothing loads every row, so the page costs the same
    at 10 dashboards or 10,000. Metrics, goals and reports have their own
    overview (:class:`GoalsIndexView`).

    Each section sorts on its own (``?dash=``, ``?playlists=``,
    ``?components=``; :func:`section_sort`) and its columns resize; the cards
    view has a Sort select instead of headers. A sort swaps the whole body, so
    every link stays current. Sorting by something that isn't a column (cards,
    opens on, round, design, metric) loads that section's rows, only then."""

    template_name = "dashboards/index.html"

    #: How many of each the overview shows; the rest are on the paged lists.
    DASHBOARD_CARDS = 8
    DASHBOARD_ROWS = 20
    PLAYLISTS = 6
    COMPONENTS = 6

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack.api import apply_ordering

        context = super().get_context_data(**kwargs)
        request = self.request
        user = request.user
        boards_view = "list" if request.GET.get("boards") == "list" else "cards"
        board_limit = self.DASHBOARD_ROWS if boards_view == "list" else self.DASHBOARD_CARDS

        # -- dashboards
        dash_order, dash_links = section_sort(
            request,
            "dash",
            ("name", "cards", "opens", "updated_at"),
            "-updated_at",
            largest_first=("cards", "updated_at"),
        )
        tag = request.GET.get("tag", "").strip()
        board_qs = Dashboard.objects.visible_to(user).active().tagged(tag).select_related("owner")
        dash_key, dash_desc = dash_order.lstrip("-"), dash_order.startswith("-")
        if dash_key == "cards":
            boards = sorted(board_qs, key=lambda d: (len(d.layout), d.name.lower()), reverse=dash_desc)[:board_limit]
        elif dash_key == "opens":
            boards = sorted(
                board_qs,
                key=lambda d: (period_heading(d.default_period or None).lower(), d.name.lower()),
                reverse=dash_desc,
            )[:board_limit]
        else:
            boards = list(apply_ordering(board_qs, f"{dash_order},name", {"name", "updated_at"})[:board_limit])

        # -- playlists
        playlists_order, playlists_links = section_sort(
            request, "playlists", ("name", "round", "updated_at"), "-updated_at", largest_first=("round", "updated_at")
        )
        playlist_qs = Playlist.objects.visible_to(user).active().tagged(tag)
        if playlists_order.lstrip("-") == "round":
            # How long a round takes depends on the slides this viewer can open.
            timed = [(p, sum(sl["seconds"] for sl in playlist_slides(p, user))) for p in playlist_qs]
            timed.sort(key=lambda pair: (pair[1], pair[0].name.lower()), reverse=playlists_order.startswith("-"))
            playlists = [p for p, _seconds in timed[: self.PLAYLISTS]]
        else:
            playlists = list(
                apply_ordering(playlist_qs, f"{playlists_order},name", {"name", "updated_at"})[: self.PLAYLISTS]
            )

        # -- components
        components_order, components_links = section_sort(
            request,
            "components",
            ("name", "type", "metric", "updated_at"),
            "-updated_at",
            largest_first=("updated_at",),
        )
        component_qs = Component.objects.visible_to(user).active().tagged(tag)
        comp_key, comp_desc = components_order.lstrip("-"), components_order.startswith("-")
        metric_names: dict[str, str] = {}
        if comp_key == "type":
            # By what the table shows: the design's label and the metric's name, not their keys.
            def design(card: Component) -> str:
                ct = get_component_type(card.type)
                return str(ct.label if ct else card.type).lower()

            components = sorted(component_qs, key=lambda c: (design(c), c.name.lower()), reverse=comp_desc)
        elif comp_key == "metric":
            metric_names = dict(Metric.objects.values_list("key", "name"))
            components = sorted(
                component_qs,
                key=lambda c: (str(metric_names.get(c.metric, c.metric)).lower(), c.name.lower()),
                reverse=comp_desc,
            )
        else:
            components = list(
                apply_ordering(component_qs, f"{components_order},name", {"name", "updated_at"})[: self.COMPONENTS]
            )
        components = components[: self.COMPONENTS]
        if not metric_names:
            metric_names = dict(
                Metric.objects.filter(key__in=[c.metric for c in components]).values_list("key", "name")
            )

        context.update(
            {
                "dashboards": [
                    {"dashboard": d, "opens": period_heading(d.default_period) if d.default_period else ""}
                    for d in boards
                ],
                "dashboard_count": board_qs.count(),
                "boards_view": boards_view,
                "dash_sort": dash_links,
                "dash_order": dash_order,
                "dash_default": dash_order == "-updated_at",
                "dash_choices": [
                    ("-updated_at", "Recently changed"),
                    ("name", "Name, A to Z"),
                    ("-name", "Name, Z to A"),
                    ("-cards", "Most cards"),
                    ("cards", "Fewest cards"),
                ],
                "dash_keep": [(k, v) for k, v in request.GET.items() if k != "dash"],
                "playlists": [self.playlist_row(p, user) for p in playlists],
                "playlist_count": playlist_qs.count(),
                "playlists_sort": playlists_links,
                "components": [self.component_row(c, metric_names, user) for c in components],
                "component_count": component_qs.count(),
                "components_sort": components_links,
                # The first-run steps start from a metric, wherever they're made.
                "metric_count": Metric.objects.visible_to(user).active().count(),
                "tag": tag,
                "tags": tag_cloud(
                    *(m.objects.visible_to(user).active() for m in (Dashboard, Playlist, Component)), current=tag
                ),
                "archived": archived_links(user, Dashboard, Playlist, Component),
                "can_build": bool(readable_datasets(user)),
            }
        )
        return context

    @staticmethod
    def component_row(card: Component, metric_names: dict[str, str], user: Any) -> dict[str, Any]:
        ct = get_component_type(card.type)
        return {
            "component": card,
            # A card's page is its builder; staff can see someone's personal card but not edit it.
            "url": card.get_absolute_url() if card.can_edit(user) else "",
            "type_label": ct.label if ct else card.type,
            "icon": ct.icon if ct else "",
            "metric_name": metric_names.get(card.metric, card.metric),
        }

    @staticmethod
    def playlist_row(playlist: Playlist, user: Any) -> dict[str, Any]:
        slides = playlist_slides(playlist, user)
        seconds = sum(s["seconds"] for s in slides)
        return {
            "playlist": playlist,
            "count": len(slides),
            "strip": slides[:4],
            "round": f"{seconds // 60} min {seconds % 60} s" if seconds >= 60 else f"{seconds} s",
        }


def section_sort(
    request: HttpRequest, param: str, keys: tuple[str, ...], default: str, *, largest_first: tuple[str, ...] = ()
) -> tuple[str, dict[str, dict[str, str]]]:
    """One table's sort on a page that has several: ``?<param>=key`` (``-``
    for descending), validated against *keys*, else *default*. Returns
    ``(order, links)`` — per key ``{url, aria_sort}``, the URL keeping every
    other query parameter (the period, the other tables' sorts). A click sorts
    A–Z, or largest first for the *largest_first* keys; a second click flips it."""
    raw = request.GET.get(param, "").strip()
    order = raw if raw.lstrip("-") in keys else default
    links = {}
    for key in keys:
        if order == key:
            nxt, aria = f"-{key}", "ascending"
        elif order == f"-{key}":
            nxt, aria = key, "descending"
        else:
            nxt, aria = (f"-{key}" if key in largest_first else key), "none"
        params = request.GET.copy()
        params[param] = nxt
        links[key] = {"url": f"?{params.urlencode()}", "aria_sort": aria}
    return order, links


def usage_words(usage: Optional[dict[str, int]]) -> str:
    """One metric's :func:`usage_index` row as words — "2 boards, 1 report,
    1 goal list" — or "" when it's drawn nowhere."""
    if not usage:
        return ""
    nouns = (
        ("boards", "board"),
        ("reports", "report"),
        ("goal_lists", "goal list"),
        ("components", "card"),
        ("rates", "rate"),
    )
    parts = [f"{usage[key]} {noun}{'s' if usage[key] != 1 else ''}" for key, noun in nouns if usage.get(key)]
    return ", ".join(parts)


class GoalsIndexView(LoginRequiredMixin, TemplateView):
    """``/smallstack/goals/`` — the Goals overview: goal lists (each one's
    summary loaded as it scrolls into view), the metrics behind them with what
    each says right now (``?period=``, compared with the period before), and
    the reports that compare them over periods. A few of each; the full lists
    are paged.

    Each section is a table with its own sort (``?lists=``, ``?metrics=``,
    ``?reports=``; :func:`section_sort`). The server renders every section
    either way, so a sort swaps the whole page body and all links stay current.
    Names and dates sort the whole set before the few are taken; a metric's
    value sorts the metrics shown (each one is evaluated); a report's
    movement evaluates every report, as on the reports list."""

    template_name = "dashboards/goals_index.html"

    #: Metrics shown with live values (each one is evaluated and compared).
    LIVE_METRICS = 24
    REPORTS = 8
    GOAL_LISTS = 8

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack.api import apply_ordering

        from .metrics import _is_number as is_number
        from .reports import sort_by_movement

        context = super().get_context_data(**kwargs)
        request = self.request
        user = request.user
        period = requested_period(request)
        labels = {d.key: d.label for d in all_defs()}

        # -- goal lists
        lists_order, lists_links = section_sort(
            request, "lists", ("name", "goals", "updated_at"), "-updated_at", largest_first=("goals", "updated_at")
        )
        tag = request.GET.get("tag", "").strip()
        goal_qs = GoalList.objects.visible_to(user).active().tagged(tag)
        goal_count = goal_qs.count()
        if lists_order.lstrip("-") == "goals":
            lists = sorted(goal_qs, key=lambda g: (len(g.goals()), g.name.lower()), reverse=lists_order.startswith("-"))
        else:
            lists = list(apply_ordering(goal_qs, lists_order, {"name", "updated_at"})[: self.GOAL_LISTS])

        # -- metrics
        from .models import usage_index

        metrics_order, metrics_links = section_sort(
            request, "metrics", ("name", "source", "value", "used"), "name", largest_first=("value", "used")
        )
        metric_qs = Metric.objects.visible_to(user).active().tagged(tag).select_related("owner")
        # Where each metric is drawn, once for the whole list; ?unused=1 keeps
        # only the ones drawn nowhere — the pile to clear.
        usage = usage_index(user)
        unused_only = request.GET.get("unused") == "1"
        if unused_only:
            metric_qs = metric_qs.exclude(key__in=list(usage))
        metric_count = metric_qs.count()
        if metrics_order.lstrip("-") == "source":
            shown = sorted(
                metric_qs,
                key=lambda m: (str(labels.get(m.dataset) or m.source_label).lower(), m.name.lower()),
                reverse=metrics_order.startswith("-"),
            )[: self.LIVE_METRICS]
        else:
            name_order = metrics_order if metrics_order.lstrip("-") == "name" else "name"
            shown = list(apply_ordering(metric_qs, name_order, {"name"})[: self.LIVE_METRICS])
        rows = []
        for m in shown:
            result = evaluate(m, request, period=period)
            rows.append(
                {
                    "metric": m,
                    "result": result,
                    "reading": plain_reading(m.filter_summary),
                    "source": m.source_label if m.source != "dataset" else labels.get(m.dataset, m.dataset),
                    "comparison": compare_with_previous(m, request, period, result),
                    "all_time": bool(period) and not m.period_field,
                    "usage": usage.get(m.key),
                    "used_in": usage_words(usage.get(m.key)),
                }
            )
        if metrics_order.lstrip("-") == "value":
            numeric = [r for r in rows if r["result"].ok and is_number(r["result"].value)]
            rest = [r for r in rows if not (r["result"].ok and is_number(r["result"].value))]
            numeric.sort(key=lambda r: float(r["result"].value), reverse=metrics_order.startswith("-"))
            rows = numeric + rest
        elif metrics_order.lstrip("-") == "used":
            rows.sort(key=lambda r: (r["usage"] or {}).get("total", 0), reverse=metrics_order.startswith("-"))
        unused_params = request.GET.copy()
        if unused_only:
            unused_params.pop("unused", None)
        else:
            unused_params["unused"] = "1"
        metrics_links["unused"] = {"url": f"?{unused_params.urlencode()}", "aria_sort": "none"}

        # -- reports
        reports_order, reports_links = section_sort(
            request, "reports", ("name", "movement", "updated_at"), "-updated_at", largest_first=("updated_at",)
        )
        report_qs = Report.objects.visible_to(user).active().tagged(tag).select_related("owner")
        report_count = report_qs.count()
        movements: dict[int, Any] = {}
        if reports_order.lstrip("-") == "movement":
            ranked = sort_by_movement(list(report_qs), request, desc=reports_order.startswith("-"))[: self.REPORTS]
            movements = {r.pk: m for r, m in ranked}
            reports = [r for r, _m in ranked]
        else:
            reports = list(apply_ordering(report_qs, reports_order, {"name", "updated_at"})[: self.REPORTS])

        context.update(
            {
                "metric_rows": rows,
                "metric_count": metric_count,
                "unused_only": unused_only,
                "tag": tag,
                "tags": tag_cloud(
                    *(m.objects.visible_to(user).active() for m in (GoalList, Metric, Report)), current=tag
                ),
                "archived": archived_links(user, GoalList, Metric, Report),
                "unused_count": (
                    metric_count
                    if unused_only
                    else Metric.objects.visible_to(user).active().tagged(tag).exclude(key__in=list(usage)).count()
                ),
                "period": period or "all",
                "period_heading": period_heading(period).lower(),
                "index_periods": [
                    {"key": k, "label": lbl, "current": k == (period or "all")} for k, lbl in SHORT_PERIODS
                ],
                "reports": [
                    {
                        "report": r,
                        "columns": join_words([period_heading(p).lower() for p in r.periods]),
                        "digest_url": reverse("dashboards_report_digest", kwargs={"slug": r.slug}),
                        "movement": movements.get(r.pk),
                        "sorted_by_movement": bool(movements),
                    }
                    for r in reports
                ],
                "report_count": report_count,
                "goal_lists": [
                    {
                        "goal_list": g,
                        "count": len(g.goals()),
                        "digest_url": reverse("dashboards_goals_digest", kwargs={"slug": g.slug}),
                    }
                    for g in lists[: self.GOAL_LISTS]
                ],
                "goal_list_count": goal_count,
                "can_build": bool(readable_datasets(user)),
                "lists_sort": lists_links,
                "metrics_sort": metrics_links,
                "reports_sort": reports_links,
            }
        )
        return context


class MyDashboardsView(LoginRequiredMixin, TemplateView):
    """Your dashboards, most recently changed first — the counterpart of My
    blogs: the personal ones you own and the shared ones you made
    (``OwnedQuerySet.mine``). As cards, or as a table (``?view=table``) whose
    headers sort (``?ordering=name|cards|updated_at``, ``-`` for descending —
    names ignoring case, like every list) and whose columns resize."""

    template_name = "dashboards/my_dashboards.html"
    #: Header sorts: the database ones go through the framework's one ordering
    #: choke point; ``cards`` (the layout's length) sorts here.
    SORTS = ("name", "cards", "updated_at")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack.api import apply_ordering

        context = super().get_context_data(**kwargs)
        request = self.request
        user = request.user
        ordering = request.GET.get("ordering", "").strip()
        field = ordering.lstrip("-")
        if field not in self.SORTS:
            ordering, field = "", ""
        tag = request.GET.get("tag", "").strip()
        mine = Dashboard.objects.mine(user).visible_to(user).active()
        qs: QuerySet = mine.tagged(tag).order_by("-updated_at", "name")
        if field in ("name", "updated_at"):
            qs = apply_ordering(qs, ordering, {"name", "updated_at"})
        rows: Any = qs
        if field == "cards":
            # Not a column: this sort reads them all, then pages what it sorted.
            rows = sorted(qs, key=lambda d: (len(d.layout), d.name.lower()), reverse=ordering.startswith("-"))
        per_page = page_size_from(request, PAGE_SIZE_CHOICES)
        page = paginate_queryset(rows, request, page_size=per_page)
        boards = list(page.object_list)
        context.update(
            {
                "page_obj": page,
                "page_sizes": PAGE_SIZE_CHOICES,
                "per_page": per_page,
                "board_count": page.paginator.count,
                "tag": tag,
                "tags": tag_cloud(mine, current=tag),
            }
        )
        context["boards"] = [
            {
                "dashboard": d,
                "cards": len(d.layout),
                "opens": period_heading(d.default_period).lower() if d.default_period else "all time",
                "digest_url": reverse("dashboards_digest", kwargs={"slug": d.slug}),
                "edit_url": reverse("dashboards/boards-update", kwargs={"pk": d.pk}) if d.can_edit(user) else "",
            }
            for d in boards
        ]
        context["view"] = "table" if request.GET.get("view") == "table" else "cards"
        context["ordering"] = ordering
        context["sort_links"] = self.sort_links(request, ordering)
        context["shared_count"] = (
            Dashboard.objects.visible_to(user).filter(owner__isnull=True).exclude(created_by=user).count()
        )
        # Other people's personal dashboards shared with this person: a strip of
        # their own, since "my dashboards" shouldn't mean someone else's.
        context["shared_with_me"] = list(
            Dashboard.objects.shared_with_me(user).active().select_related("owner").order_by("-updated_at", "name")[:24]
        )
        return context

    def sort_links(self, request: HttpRequest, ordering: str) -> dict[str, dict[str, str]]:
        """Per sortable header: ``{url, aria_sort}`` — a click sorts ascending,
        a second click descending; other query params ride along."""
        out = {}
        for name in self.SORTS:
            params = request.GET.copy()
            params.pop("page", None)  # a new order starts at its first page
            if ordering == name:
                params["ordering"], aria = f"-{name}", "ascending"
            elif ordering == f"-{name}":
                params["ordering"], aria = name, "descending"
            else:
                # Dates read newest first on the first click; text and counts A→Z / low→high.
                params["ordering"], aria = (f"-{name}" if name == "updated_at" else name), "none"
            out[name] = {"url": f"{request.path}?{params.urlencode()}", "aria_sort": aria}
        return out


class DashboardPageView(LoginRequiredMixin, TemplateView):
    template_name = "dashboards/dashboard.html"

    def get_dashboard(self) -> Dashboard:
        return visible_or_404(Dashboard.objects.all(), self.request, slug=self.kwargs["slug"])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        user = request.user
        dashboard = self.get_dashboard()
        period = requested_period(request, dashboard.default_period)
        can_edit = dashboard.can_edit(user)
        # What each card's menu needs, for someone who can edit the dashboard:
        # the saved card a cell places (and how many dashboards show it), and
        # the metric it draws. A viewer's menu needs neither.
        placed = {c.get("component") for c in dashboard.layout if c.get("component")}
        saved_cards = {c.key: c for c in Component.objects.filter(key__in=placed)} if can_edit and placed else {}
        shown_on = placement_counts(set(saved_cards))
        metrics = {m.key: m for m in Metric.objects.filter(key__in=dashboard.metric_keys())} if can_edit else {}
        cells = []
        for cell in dashboard.layout:
            if dashboard.system_key and widget_refused(cell, user):
                continue  # the shared system board leaves out what the viewer can't read (T5-9)
            ct = get_component_type(str(cell.get("type", "")))
            type_label = ct.label if ct else cell.get("type")
            where = {"slug": dashboard.slug, "cell_id": cell.get("id", "")}
            saved = cell.get("component")
            card = saved_cards.get(saved)
            metric = metrics.get(cell.get("metric"))
            # Other dashboards change when this card does: worth marking, and worth a way out.
            linked = card is not None and shown_on.get(card.key, 0) > 1
            own_metric = metric is not None and not metric.is_manual and metric.can_view(user)
            cells.append(
                {
                    **cell,
                    "type_label": type_label,
                    # What the card's menu calls it, and where its entries lead.
                    "label": cell.get("title") or cell.get("name") or type_label,
                    # A saved card is edited where it's placed only by someone who may
                    # edit the card itself; any other card belongs to this dashboard.
                    "edit_url": reverse("dashboards_card_edit", kwargs=where)
                    if can_edit and cell.get("id") and (not saved or (card is not None and card.can_edit(user)))
                    else "",
                    "metric_url": reverse("dashboards_metric_detail", kwargs={"key": cell["metric"]})
                    if metric is not None and metric.can_view(user)
                    else "",
                    "metric_edit_url": reverse("dashboards/metrics-update", kwargs={"pk": metric.pk})
                    if metric is not None and metric.can_edit(user)
                    else "",
                    "metric_name": metric.name if metric is not None else "",
                    "metric_copyable": own_metric,
                    "linked": linked,
                    "saved_name": card.name if card is not None else "",
                    "saved_count": shown_on.get(card.key, 0) if card is not None else 0,
                    # "Make a unique copy" for a card other dashboards show too; "Give it
                    # its own metric" for a card of this dashboard that shares its number.
                    "copy_url": reverse("dashboards_card_copy", kwargs=where)
                    if can_edit and cell.get("id") and (linked or (not saved and own_metric))
                    else "",
                }
            )
        context.update(
            {
                "dashboard": dashboard,
                "cells": cells,
                "period": period or "all",
                "period_choices": period_choices(period),
                **period_nav(period),
                "can_edit": can_edit,
                "has_period_cells": any(c.get("metric") or c.get("dataset") for c in dashboard.layout),
            }
        )
        if can_edit:
            context["editor"] = self.editor(dashboard, user)
        return context

    @staticmethod
    def editor(dashboard: Dashboard, user: Any) -> dict[str, Any]:
        """What edit mode offers: the layout, the card types, the metrics this
        dashboard may show (shared ones, plus its owner's), and staff widgets."""
        metrics = Metric.objects.visible_to(user).active()
        if dashboard.owner_id is None:
            metrics = metrics.filter(owner__isnull=True)
        else:
            metrics = metrics.filter(owner__isnull=True) | metrics.filter(owner_id=dashboard.owner_id)
        cards = Component.objects.visible_to(user).active().filter(owner__isnull=True)
        if dashboard.owner_id is not None:
            cards = cards | Component.objects.active().filter(owner_id=dashboard.owner_id)
        return {
            # Cards the page leaves out for this viewer stay out of edit mode too;
            # the save keeps them where they were (G3-1).
            "layout": visible_layout(dashboard, user),
            "types": describe_types(user),
            # Saved cards this dashboard may place: shared ones, and its owner's.
            "components": [
                {"key": c.key, "name": c.name, "type": c.type}
                for c in cards.order_by("name")
                if get_component_type(c.type) is not None
            ],
            "metrics": [
                {"key": m.key, "name": m.name, "dataset": m.dataset}
                for m in metrics.order_by("name")
                if may_read(m, user)
            ],
            "widgets": [{"key": k, "title": w.title} for k, w, _i in available_widgets()]
            if getattr(user, "is_staff", False)
            else [],
        }


class AdminHomeView(DashboardPageView):
    """The ``/smallstack/`` page, drawn as the system dashboard
    ``ADMIN_HOME_KEY``: the widgets apps publish, as cards staff can
    rearrange, resize, remove, and mix with metric cards. Registered with
    ``apps.smallstack.dashboard.set_dashboard_page`` in ``apps.py``; the
    route and its staff check stay with SmallStackDashboardView."""

    template_name = "dashboards/admin_home.html"

    def get_dashboard(self) -> Dashboard:
        return system_dashboard(ADMIN_HOME_KEY, name="SmallStack", description="System overview at a glance")


class DashboardCellView(LoginRequiredMixin, View):
    """One cell's HTML — what each grid item's ``hx-get`` loads."""

    def get(self, request: HttpRequest, slug: str, cell_id: str) -> HttpResponse:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        cell = dashboard.cell(cell_id)
        if cell is None:
            raise Http404
        period = requested_period(request, dashboard.default_period)
        # ?narrow=: the slice a linked card sent this one (options.listen; cards.js).
        return HttpResponse(render_cell(dashboard, cell, request, period, narrow=request.GET.get("narrow", "")))


class DashboardLayoutView(LoginRequiredMixin, View):
    """Edit mode's Save: the client posts the whole layout; the model validates
    it (``Dashboard.clean`` → ``normalize_layout``). Client state is
    authoritative — one write, no per-cell endpoints to keep consistent."""

    def post(self, request: HttpRequest, slug: str) -> JsonResponse:
        dashboard = get_object_or_404(Dashboard, slug=slug)
        if not dashboard.can_edit(request.user):
            return JsonResponse({"errors": ["You may not edit this dashboard."]}, status=403)
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"errors": ["Body must be JSON."]}, status=400)
        layout = payload.get("layout") if isinstance(payload, dict) else None
        if not isinstance(layout, list):
            return JsonResponse({"errors": ['Send {"layout": [...]}.']}, status=400)
        dashboard.layout = keep_hidden_cells(dashboard, layout, request.user)
        try:
            dashboard.save()
        except ValidationError as exc:
            return JsonResponse({"errors": exc.message_dict.get("layout", exc.messages)}, status=400)
        return JsonResponse({"ok": True, "layout": dashboard.layout})


class DashboardCardEditView(LoginRequiredMixin, View):
    """Edit one card where it sits: the component builder, in a dialog on the
    dashboard page (the card menu's "Edit card"; ``dashboard.js`` loads this
    fragment and posts its form back).

    Two kinds of card, one builder (``includes/component_builder.html``):

    - **a saved card** (the cell names a ``Component``): the component itself is
      edited, by someone who may edit it, and ``signals.py`` refreshes every
      dashboard showing it — the same save as the builder's own page;
    - **a card of this dashboard only**: its type, metric, options and title
      are written back into this dashboard's layout, which
      ``Dashboard.clean`` validates as it does a whole layout.

    A saved GET is the fragment; a POST that saves answers ``{"ok": true}`` and
    one that doesn't answers the fragment again, with what was wrong (422)."""

    template_name = "dashboards/partials/card_edit.html"

    def _card(self, request: HttpRequest, slug: str, cell_id: str) -> tuple[Dashboard, dict[str, Any], Any]:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        if not dashboard.can_edit(request.user):
            raise PermissionDenied
        cell = dashboard.cell(cell_id)
        if cell is None:
            raise Http404("This dashboard has no such card.")
        saved = Component.objects.filter(key=cell.get("component") or "").first() if cell.get("component") else None
        if saved is not None and not saved.can_edit(request.user):
            raise PermissionDenied
        return dashboard, cell, saved

    def _render(
        self, request: HttpRequest, dashboard: Dashboard, cell: dict[str, Any], saved: Any, form: Any, status: int = 200
    ) -> HttpResponse:
        context = {
            "dashboard": dashboard,
            "form": form,
            "object": saved,
            "cb_mode": "placed" if saved is not None else "cell",
            "cb_action": reverse("dashboards_card_edit", kwargs={"slug": dashboard.slug, "cell_id": cell["id"]}),
            "cb_visibility": "shared" if dashboard.is_shared else "personal",
            "cell_errors": getattr(form, "cell_errors", []),
        }
        return render(request, self.template_name, context, status=status)

    @staticmethod
    def _cell_form(request: HttpRequest, dashboard: Dashboard, values: dict[str, Any]) -> Any:
        """The builder's form for a card that isn't a Component: never saved,
        only drawn, so it carries the cell's values as its initial ones."""
        return ComponentForm(instance=Component(owner_id=dashboard.owner_id), initial=values, user=request.user)

    def get(self, request: HttpRequest, slug: str, cell_id: str) -> HttpResponse:
        dashboard, cell, saved = self._card(request, slug, cell_id)
        if saved is not None:
            form = ComponentForm(instance=saved, user=request.user)
        else:
            values = {
                "name": cell.get("title", ""),
                "type": cell.get("type", ""),
                "metric": cell.get("metric", ""),
                "options": cell.get("options") or {},
                **{k: cell.get(k, {} if k == "filter_tree" else "") for k in SOURCE_KEYS},
            }
            form = self._cell_form(request, dashboard, values)
        return self._render(request, dashboard, cell, saved, form)

    def post(self, request: HttpRequest, slug: str, cell_id: str) -> HttpResponse:
        dashboard, cell, saved = self._card(request, slug, cell_id)
        if saved is not None:
            form = ComponentForm(request.POST, instance=saved, user=request.user)
            if form.is_valid():
                form.save()
                return JsonResponse({"ok": True})
            return self._render(request, dashboard, cell, saved, form, status=422)

        posted = request.POST
        kind = posted.get("type", "").strip()
        metric = posted.get("metric", "").strip()
        title = posted.get("name", "").strip()[:120]
        try:
            options = json.loads(posted.get("options") or "{}")
        except ValueError:
            options = None
        ct = get_component_type(kind)
        problems: list[str] = []
        if ct is None or (ct.visible_to is not None and not ct.visible_to(request.user)):
            problems.append("Pick a card type you can use.")
        if not isinstance(options, dict):
            problems.append("The card's options didn't arrive as they should. Reload the page and try again.")
            options = {}
        # The card keeps its place and size; everything it draws comes from the form.
        fresh: dict[str, Any] = {k: cell[k] for k in ("id", "x", "y", "w", "h") if k in cell}
        fresh.update({"type": kind, "options": options})
        if ct is not None and ct.needs_metric:
            if metric:
                fresh["metric"] = metric
            elif posted.get("dataset", "").strip():
                # The card's own source, as the builder's form posts it (ComponentForm's fields).
                try:
                    tree = json.loads(posted.get("filter_tree") or "{}")
                except ValueError:
                    tree = None
                if not isinstance(tree, dict):
                    problems.append("The card's filter didn't arrive as it should. Reload the page and try again.")
                    tree = {}
                fresh.update(
                    {
                        "dataset": posted["dataset"].strip(),
                        "filter_tree": tree,
                        "agg": posted.get("agg", "count").strip() or "count",
                        "measure": posted.get("measure", "").strip(),
                        "period_field": posted.get("period_field", "").strip(),
                    }
                )
        if title:
            fresh["title"] = title
        if not problems:
            before = dashboard.layout
            dashboard.layout = [fresh if c.get("id") == cell_id else c for c in before]
            try:
                dashboard.save()
            except ValidationError as exc:
                dashboard.layout = before
                found = exc.message_dict.get("layout", exc.messages) if hasattr(exc, "message_dict") else exc.messages
                # "layout[2].options: …" names a position the person never saw.
                problems = [re.sub(r"^layout\[\d+\]\.?:?\s*", "", str(m)) for m in found]
            else:
                return JsonResponse({"ok": True})
        form = self._cell_form(request, dashboard, {"name": title, "type": kind, "metric": metric, "options": options})
        form.cell_errors = problems
        return self._render(request, dashboard, cell, None, form, status=422)


class DashboardShareView(LoginRequiredMixin, View):
    """Share a personal dashboard with everyone who can sign in, or with
    people by name — the dialog in the stat modal (the header's **Share**).
    Each change posts back and redraws the dialog; ``?q=`` finds people."""

    template_name = "dashboards/partials/share_dialog.html"
    MATCHES = 8

    def dashboard(self, request: HttpRequest, slug: str) -> Dashboard:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        if not dashboard.can_edit(request.user) or dashboard.owner_id is None:
            raise PermissionDenied("Only a personal dashboard's owner shares it.")
        return dashboard

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        dashboard = self.dashboard(request, slug)
        if not request.headers.get("HX-Request"):
            return redirect(dashboard.get_absolute_url())
        return self.render(request, dashboard)

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        dashboard = self.dashboard(request, slug)
        everyone = None
        if "everyone_sent" in request.POST:
            everyone = request.POST.get("everyone") in ("1", "on", "true")
        add = [u for u in request.POST.getlist("add") if u]
        remove = [u for u in request.POST.getlist("remove") if u]
        set_sharing(dashboard, actor=request.user, everyone=everyone, add=add, remove=remove)
        if not request.headers.get("HX-Request"):
            return redirect(dashboard.get_absolute_url())
        return self.render(request, dashboard)

    def render(self, request: HttpRequest, dashboard: Dashboard) -> HttpResponse:
        from django.contrib.auth import get_user_model

        q = (request.POST.get("q") or request.GET.get("q") or "").strip()  # an Add keeps the search
        matches: list[Any] = []
        if q:
            User = get_user_model()
            # Staff search by any part of a name. Anyone else finds a person by
            # their exact username: a letter-by-letter search listed every
            # account, staff included, to any member with a dashboard.
            if request.user.is_staff:
                who = Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            else:
                who = Q(username__iexact=q)
            found = (
                User.objects.filter(is_active=True)
                .exclude(pk=dashboard.owner_id or 0)
                .exclude(pk__in=dashboard.shared_with.values("pk"))
                .filter(who)
                .order_by("username")[: self.MATCHES]
            )
            matches = [{"username": u.get_username(), "name": u.get_full_name() or u.get_username()} for u in found]
        context = {
            "dashboard": dashboard,
            "share": share_payload(dashboard),
            "q": q,
            "matches": matches,
            "share_url": reverse("dashboards_share", kwargs={"slug": dashboard.slug}),
            "link": request.build_absolute_uri(dashboard.get_absolute_url()),
        }
        return render(request, self.template_name, context)


class DashboardCardCopyView(LoginRequiredMixin, View):
    """The card menu's "Make a unique copy" and "Give it its own metric": one
    card becomes this dashboard's own, where it sits (``boards.make_card_unique``).
    ``metric=1`` copies the metric it draws as well."""

    def post(self, request: HttpRequest, slug: str, cell_id: str) -> JsonResponse:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        if not dashboard.can_edit(request.user):
            return JsonResponse({"errors": ["You may not edit this dashboard."]}, status=403)
        try:
            made = make_card_unique(dashboard, cell_id, request.user, copy_metric=request.POST.get("metric") == "1")
        except LookupError:
            return JsonResponse({"errors": ["This dashboard has no such card."]}, status=404)
        except ValidationError as exc:
            return JsonResponse({"errors": exc.messages}, status=400)
        return JsonResponse({"ok": True, **made})


class DashboardCardsView(LoginRequiredMixin, View):
    """The settings page's cards table, on its own: its headers re-sort it in
    place (``?order=``) without touching a form that may hold unsaved edits."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        cards = board_cards(dashboard, request, request.GET.get("order", ""))
        return render(request, "dashboards/partials/board_cards.html", {"cards": cards, "dashboard": dashboard})


class DashboardCardValueView(LoginRequiredMixin, View):
    """One card's value in the cards table, loaded as its row scrolls into view."""

    def get(self, request: HttpRequest, slug: str, cell_id: str) -> HttpResponse:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        cell = dashboard.cell(cell_id)
        if cell is None:
            raise Http404
        return render(
            request, "dashboards/partials/board_card_value.html", {"value": cell_value(dashboard, cell, request)}
        )


class DashboardDigestView(LoginRequiredMixin, View):
    """Whether a dashboard needs attention, in one line, at the period it opens
    on. Loaded lazily per row on the dashboards list."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        context = board_attention(dashboard, request, dashboard.default_period or None)
        return render(request, "dashboards/partials/dashboard_digest.html", context)


class MetricDetailView(LoginRequiredMixin, TemplateView):
    template_name = "dashboards/metric_detail.html"
    ENTRIES_SHOWN = 26  # about half a year of weekly values

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        metric = visible_or_404(Metric.objects.all(), request, key=kwargs["key"])
        period = requested_period(request)
        result = evaluate(metric, request, period=period)
        drill = None
        drill_error = None
        if result.ok and metric.source == "dataset":
            try:
                # The same header sorting as the rows modal (?order=, validated).
                order = MetricRowsView.drill_order(request, metric)
                drill = drill_rows(metric, request, period=period, limit=20, order=order)
                MetricRowsView.sort_links(request, drill)
            except (FilterTreeError, ValueError) as exc:
                drill_error = str(exc)
        context.update(
            {
                "metric": metric,
                "result": result,
                "period": period or "all",
                **period_nav(period),
                "sentence": metric_sentence(metric, result),
                "comparison": compare_with_previous(metric, request, period, result),
                "rules": threshold_legend(metric),
                "drill": drill,
                "drill_total": f"{drill['total']:,}" if drill else "",
                "drill_error": drill_error,
                "usage": metric_usage(metric, request.user),
                "can_edit": metric.can_edit(request.user),
                **self.source_context(metric, period),
                "filter_json": json.dumps(metric.filter_tree, indent=2),
                "thresholds_json": json.dumps(metric.thresholds, indent=2),
                "api_url": request.build_absolute_uri(
                    reverse("dashboards_api_metric_value", kwargs={"key": metric.key})
                ),
            }
        )
        return context


    def source_context(self, metric: Metric, period: Optional[str]) -> dict[str, Any]:
        """What a hand-entered metric's or a rate's page shows in place of rows."""
        request = self.request
        if metric.is_rate:
            parts = [p for p in rate_parts(metric) if p is not None and p.can_view(request.user)]
            return {"parts": [{"metric": p, "result": evaluate(p, request, period=period)} for p in parts]}
        if not metric.is_manual:
            return {}
        entries = visible_entries(request.user).filter(metric=metric).select_related("entered_by")
        total = entries.count()
        # ?edit=<date> fills the form with that entry, to correct it.
        edit_day = parse_day(request.GET.get("edit", ""))
        editing = entries.filter(date=edit_day).first() if edit_day else None
        limit = total if request.GET.get("entries") == "all" else self.ENTRIES_SHOWN
        return {
            "entries": [
                {"entry": e, "display": format_value(e.value, metric.format, metric.unit)} for e in entries[:limit]
            ],
            "entries_total": total,
            "entries_more": max(total - limit, 0),
            "editing": editing,
            # 5.5, as it was typed, not the column's 5.5000.
            "editing_value": format(editing.value.normalize(), "f") if editing else "",
            "entry_date": editing.date if editing else timezone.localdate(),
            "entry_max_date": timezone.localdate(),
        }


class MetricEntrySaveView(LoginRequiredMixin, View):
    """Save one value of a hand-entered metric, from its page. Same date = replace."""

    def post(self, request: HttpRequest, key: str) -> HttpResponse:
        metric = _editable_manual_metric(request, key)
        day, value, errors = parse_entry(request.POST.get("date"), request.POST.get("value"))
        if errors:
            for message in errors.values():
                messages.error(request, message)
        elif day is not None and value is not None:
            record_entry(metric, day, value, request.POST.get("note", "").strip(), by=request.user)
            messages.success(request, f"Saved the value for {day:%b} {day.day}, {day.year}.")
        return redirect(metric.get_absolute_url())


class MetricEntryDeleteView(LoginRequiredMixin, View):
    """Remove one value of a hand-entered metric."""

    def post(self, request: HttpRequest, key: str, day: str) -> HttpResponse:
        metric = _editable_manual_metric(request, key)
        parsed = parse_day(day)
        if parsed is None or not delete_entry(metric, parsed):
            raise Http404("No value for that date.")
        messages.success(request, f"Removed the value for {parsed:%b} {parsed.day}, {parsed.year}.")
        return redirect(metric.get_absolute_url())


def parse_day(raw: str) -> Optional[date]:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _editable_manual_metric(request: HttpRequest, key: str) -> Metric:
    metric = visible_or_404(Metric.objects.all(), request, key=key)
    if not metric.is_manual:
        raise Http404("This metric isn't entered by hand.")
    if not metric.can_edit(request.user):
        raise PermissionDenied
    return metric


def drill_context(
    request: HttpRequest, metric: Metric, drill: dict[str, Any], period: Optional[str], narrow: Any = None
) -> dict[str, Any]:
    """The ``drill_rows.html`` fragment's context — shared by a saved metric's
    rows and an unsaved one's, so the modal reads the same either way."""
    ds = get_dataset(metric.dataset)
    applied = period if (period and metric.period_field) else None
    narrowed = plain_reading(describe_filter_tree(narrow, ds.column_labels() if ds else {})) if narrow else ""
    return {
        "drill": drill,
        "metric": metric,
        "total": f"{drill['total']:,}",
        "source": ds.dfn.label if ds is not None else metric.dataset,
        "reading": plain_reading(metric.filter_summary),
        "narrowed": narrowed,
        "when": period_phrase(applied) if applied else "",
    }


class MetricRowsView(LoginRequiredMixin, View):
    """The rows behind a card — the stat-modal fragment. ``?narrow=<tree>``
    (a grouped card's group) is AND-ed on, so it can only narrow. Period links
    reload the fragment in place; with ``retitle=1`` it also renames the modal."""

    def get(self, request: HttpRequest, key: str) -> HttpResponse:
        metric = visible_or_404(Metric.objects.all(), request, key=key)
        return self.rows(request, metric)

    def rows(self, request: HttpRequest, metric: Metric) -> HttpResponse:
        """The fragment (or CSV) for *metric*: a saved one, or a card's own
        source (:class:`CellRowsView`), which has no page of its own."""
        if not may_read(metric, request.user):
            raise Http404
        if metric.is_rate and request.GET.get("format") != "csv":
            # Cards open this modal whatever the metric: a rate points at its parts.
            parts = [p for p in rate_parts(metric) if p is not None]
            return render(request, "dashboards/partials/drill_rate.html", {"message": RATE_NO_ROWS, "parts": parts})
        narrow = None
        raw = request.GET.get("narrow")
        if raw:
            try:
                narrow = json.loads(raw)
            except ValueError:
                return HttpResponse("Bad narrow filter.", status=400)
        spec, problem = self.drill_spec(request, metric)
        if problem:
            return HttpResponse(problem, status=400)
        order = self.drill_order(request, metric)
        period = requested_period(request)
        if request.GET.get("format") == "csv":
            return self.export(request, metric, period, narrow, spec, order)
        try:
            drill = drill_rows(metric, request, period=period, extra_tree=narrow, spec=spec, order=order)
        except (FilterTreeError, ValueError) as exc:
            return render(request, "dashboards/partials/drill_error.html", {"message": str(exc)}, status=400)
        self.sort_links(request, drill)
        context = {**drill_context(request, metric, drill, period, narrow), "unsaved": is_inline(metric)}
        export = request.GET.copy()
        export.pop("retitle", None)
        export["format"] = "csv"
        context["export_url"] = f"{request.path}?{export.urlencode()}"
        title_parts = (metric.name, context["narrowed"], context["when"] or ("all time" if metric.period_field else ""))
        context.update(
            {
                # A chart bucket's rows are already a time range — period links would contradict it.
                "period_links": [] if _narrows_time(narrow, metric) else self.period_links(request, metric, period),
                "modal_title": ", ".join(p for p in title_parts if p) if request.GET.get("retitle") else "",
                "comparison": self.row_comparison(request, metric, period, narrow),
                "browse_url": reverse("datasets:browse", kwargs={"key": metric.dataset})
                if getattr(request.user, "is_staff", False) and get_dataset(metric.dataset) is not None
                else "",
                "sortable": True,  # a card's own rows sort by link like a metric's: the source is on the server
            }
        )
        return render(request, "dashboards/partials/drill_rows.html", context)

    @staticmethod
    def drill_spec(request: HttpRequest, metric: Metric) -> tuple[Optional[dict[str, Any]], str]:
        """The card's drill-down design from ``?drill=<json>``
        (``metrics.requested_drilldown``) — ``(spec or None, problem)``."""
        return requested_drilldown(request.GET.get("drill"), metric)

    @staticmethod
    def drill_order(request: HttpRequest, metric: Metric) -> str:
        """A clicked header's sort (``?order=<column>`` or ``-<column>``), when
        it names a column of the metric's dataset; "" otherwise."""
        return MetricRowsView.valid_order(request.GET.get("order"), metric)

    @staticmethod
    def valid_order(raw: Any, metric: Metric) -> str:
        """*raw* (``<column>`` or ``-<column>``) when it names a column of the
        metric's dataset; "" otherwise."""
        order = str(raw or "").strip()
        ds = get_dataset(metric.dataset)
        if not order or ds is None or order.lstrip("-") not in ds.column_names():
            return ""
        return order

    @staticmethod
    def sort_links(request: HttpRequest, drill: dict[str, Any]) -> None:
        """Give each column its header link: the same rows ordered by it. A
        second click flips the direction; dates and numbers start newest or
        largest first, text A–Z."""
        params = request.GET.copy()
        params.pop("retitle", None)
        current = drill.get("sort") or ""
        for c in drill["columns"]:
            name = c["name"]
            if current == name:
                c["aria_sort"], nxt = "ascending", f"-{name}"
            elif current == f"-{name}":
                c["aria_sort"], nxt = "descending", name
            else:
                first_desc = c.get("type") in ("date", "datetime", "integer", "float", "decimal")
                c["aria_sort"], nxt = "none", f"-{name}" if first_desc else name
            params["order"] = nxt
            c["sort_next"] = nxt
            c["sort_url"] = f"{request.path}?{params.urlencode()}"

    @staticmethod
    def export(
        request: HttpRequest,
        metric: Metric,
        period: Optional[str],
        narrow: Any,
        spec: Optional[dict[str, Any]],
        order: str = "",
    ) -> HttpResponse:
        """The drill-down as CSV — the modal's columns, formats and sort, up to
        ``metrics.EXPORT_LIMIT`` rows."""
        try:
            headers, rows = drill_csv(metric, request, period=period, extra_tree=narrow, spec=spec, order=order)
        except (FilterTreeError, ValueError) as exc:
            return HttpResponse(str(exc), status=400)
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{metric.key or "card"}-rows.csv"'
        writer = SafeCsvWriter(response)
        writer.writerow(headers)
        writer.writerows(rows)
        return response

    def period_links(self, request: HttpRequest, metric: Metric, period: Optional[str]) -> list[dict[str, Any]]:
        """Switch the modal's period in place, keeping any group narrowing.
        Empty for a metric without a period field — there's nothing to switch."""
        if not metric.period_field:
            return []
        base = request.path  # a metric's rows, or a card's own
        params = request.GET.copy()
        params["retitle"] = "1"
        choices = list(SHORT_PERIODS)
        if period and period not in dict(choices):
            # Opened on a period outside the short list (a report's "Last month"):
            # show it, highlighted, so the modal says which period it's on.
            choices.append((period, period_heading(period)))
        links = []
        for key, label in choices:
            params["period"] = key
            links.append({"label": label, "url": f"{base}?{params.urlencode()}", "current": key == (period or "all")})
        return links

    def row_comparison(self, request: HttpRequest, metric: Metric, period: Optional[str], narrow: Any) -> Any:
        """The row count against the previous period — only for a count metric
        on the whole metric (no group narrowing), where the rows ARE the value."""
        if metric.agg != "count" or narrow:
            return None
        return compare_with_previous(metric, request, period, evaluate(metric, request, period=period))


class CellRowsView(MetricRowsView):
    """The rows behind a dashboard card by its place (``d/<slug>/cards/<cell_id>/rows/``):
    the same fragment, CSV, sorting and period links as a saved metric's, over
    the card's own definition — or over its metric, for a viewer the dashboard
    was shared with who may not open that metric themselves. Access is the
    dashboard's: whoever may open it may read its cards' rows (the dataset's
    own access tier still applies, in ``rows``)."""

    def get(self, request: HttpRequest, slug: str, cell_id: str) -> HttpResponse:  # type: ignore[override]
        dashboard = visible_or_404(Dashboard.objects.all(), request, slug=slug)
        cell = next((c for c in dashboard.layout if isinstance(c, dict) and c.get("id") == cell_id), None)
        source = cell_source(cell) if cell is not None else None
        if source is None:
            raise Http404
        return self.rows(request, source)


def _narrows_time(narrow: Any, metric: Metric) -> bool:
    """Whether a ``?narrow=`` tree constrains the metric's period field."""
    return bool(narrow) and bool(metric.period_field) and f'"{metric.period_field}"' in json.dumps(narrow)


class MetricPreviewRowsView(LoginRequiredMixin, View):
    """The rows behind an UNSAVED metric — the builder's "See them". Same
    validation as the preview (``previews.unsaved_metric``), same fragment as
    a saved metric's rows, minus the link to a metric page that doesn't exist.
    An unsaved metric only exists in this POST's body, so a header sorts by
    posting it again with ``order`` (metric-builder.js), never by a link."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return HttpResponse("Body must be a JSON object.", status=400)
        raw_order = payload.pop("order", "")
        # A card's preview opens a group's or a bucket's rows with the card's
        # drill-down design (component-builder.js posts the card's definition).
        narrow = payload.pop("narrow", None)
        raw_drill = payload.pop("drill", None)
        metric, problems = unsaved_metric(request.user, payload)
        if metric is None or problems:
            return render(request, "dashboards/partials/drill_error.html", {"message": "; ".join(problems)}, status=400)
        period = str(payload.get("period") or "") or None
        spec, problem = requested_drilldown(
            raw_drill if isinstance(raw_drill, str) or raw_drill is None else json.dumps(raw_drill), metric
        )
        if problem:
            return render(request, "dashboards/partials/drill_error.html", {"message": problem}, status=400)
        try:
            order = MetricRowsView.valid_order(raw_order, metric)
            drill = drill_rows(metric, request, period=period, extra_tree=narrow or None, spec=spec, order=order)
            MetricRowsView.sort_links(request, drill)
        except (FilterTreeError, ValueError) as exc:
            return render(request, "dashboards/partials/drill_error.html", {"message": str(exc)}, status=400)
        context = {**drill_context(request, metric, drill, period, narrow or None), "unsaved": True}
        return render(request, "dashboards/partials/drill_rows.html", context)


class ReportPageView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        report = visible_or_404(Report.objects.all(), request, slug=slug)
        matrix = report_matrix(report, request)
        # A clicked header (?order=metric / -c0 …); the CSV follows it too.
        order = report_order(request.GET.get("order"), matrix)
        matrix = sort_report(matrix, order)
        if request.GET.get("format") == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{report.slug}.csv"'
            write_report_csv(matrix, response)
            return response
        return render(
            request,
            "dashboards/report.html",
            {
                "report": report,
                "matrix": present_report(matrix),
                "order": order,
                "sort_links": report_sort_links(matrix, order),
                "can_edit": report.can_edit(request.user),
                "api_url": request.build_absolute_uri(
                    reverse("dashboards_api_report_values", kwargs={"slug": report.slug})
                ),
            },
        )


class ReportDigestView(LoginRequiredMixin, View):
    """A report's movement in one line — up / down / unchanged between its
    first two columns. Loaded lazily per row on the reports list."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        report = visible_or_404(Report.objects.all(), request, slug=slug)
        movement = report_movement(report, request)
        if movement is None:
            return HttpResponse("")
        return render(request, "dashboards/partials/report_digest.html", movement)


# -- CRUD (HTML + REST + MCP from one class each) ------------------------------------
#
# Each CRUDView's delete page is customised with an ordinary view mixin
# (``view_mixins``), so its overrides reach the framework's view through
# ``super()``. Forms receive the signed-in user from the framework, on every
# surface (``CRUDView`` passes ``user=`` to a form that accepts it).

if TYPE_CHECKING:
    _DeleteViewBase = DeleteView
else:
    _DeleteViewBase = object


class _DeleteInModalMixin(_DeleteViewBase):
    """The list's trash icon loads the delete confirmation into the global
    modal over htmx; a direct visit gets the full page."""

    modal_template_name = ""

    def get_template_names(self) -> list[str]:
        if self.request.headers.get("HX-Request"):
            return [self.modal_template_name]
        return list(super().get_template_names())


class MetricDeleteMixin(_DeleteInModalMixin):
    """Shows which cards and report rows the delete would break, and reports
    what ``MetricCRUDView.on_delete`` removed."""

    modal_template_name = "smallstack_dashboards/crud/metric_confirm_delete_modal.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        metric = self.object
        context["usage"] = metric_usage(metric, self.request.user)
        context["reading"] = plain_reading(metric.filter_summary)
        ds = get_dataset(metric.dataset)
        context["source"] = ds.dfn.label if ds is not None else metric.dataset
        return context

    def form_valid(self, form: Any) -> HttpResponse:
        response = super().form_valid(form)
        cards, rows = getattr(self.request, "_dashboards_detached", (0, 0))
        if cards or rows:
            parts = [f"{cards} card{'s' if cards != 1 else ''}"] if cards else []
            parts += [f"{rows} report row{'s' if rows != 1 else ''}"] if rows else []
            messages.success(self.request, f"Deleted “{self.object.name}” and removed {join_words(parts)}.")
        return response


class DashboardDeleteMixin(_DeleteInModalMixin):
    """Counts what goes (cards, typed notes) and hands over the layout JSON,
    which is enough to rebuild the dashboard later."""

    modal_template_name = "smallstack_dashboards/crud/dashboard_confirm_delete_modal.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        cells = [c for c in self.object.layout if isinstance(c, dict)]
        notes = [c for c in cells if c.get("type") == "text" and (c.get("options") or {}).get("markdown")]
        context["card_count"] = len(cells)
        context["note_count"] = len(notes)
        context["metric_count"] = len({c["metric"] for c in cells if isinstance(c.get("metric"), str)})
        context["layout_json"] = json.dumps(self.object.layout, indent=2)
        return context


class ReportDeleteMixin(_DeleteInModalMixin):
    """Shows what the report compared (its rows and columns), so the person
    can be sure it's the right one."""

    modal_template_name = "smallstack_dashboards/crud/report_confirm_delete_modal.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        report = self.object
        names = dict(Metric.objects.filter(key__in=report.metric_keys()).values_list("key", "name"))
        context["columns"] = [period_heading(p) for p in report.periods] or ["All time"]
        context["metric_names"] = [
            i.get("label") or names.get(i["metric"], i["metric"]) for i in report.items if isinstance(i, dict)
        ]
        return context


class _ConfirmDeleteMixin(_DeleteInModalMixin):
    """A delete confirmation from one shared page and modal wrapper
    (``owned_confirm_*.html``) around this kind's body (``body_template``),
    told what still uses the row (:func:`where_used`)."""

    modal_template_name = "smallstack_dashboards/crud/owned_confirm_modal.html"
    body_template = ""
    kind = ""

    def get_template_names(self) -> list[str]:
        if self.request.headers.get("HX-Request"):
            return [self.modal_template_name]
        return ["smallstack_dashboards/crud/owned_confirm_page.html"]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(confirm_context(self.kind, self.object, self.request.user, "Delete"))
        context["body_template"] = self.body_template
        return context


class ComponentDeleteMixin(_ConfirmDeleteMixin):
    body_template = "smallstack_dashboards/crud/_component_delete_body.html"
    kind = "component"


class PlaylistDeleteMixin(_ConfirmDeleteMixin):
    body_template = "smallstack_dashboards/crud/_playlist_delete_body.html"
    kind = "playlist"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["slide_count"] = len([i for i in self.object.items or [] if isinstance(i, dict)])
        return context


class GoalListDeleteMixin(_ConfirmDeleteMixin):
    body_template = "smallstack_dashboards/crud/_goallist_delete_body.html"
    kind = "goals"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sections = self.object.sections if isinstance(self.object.sections, list) else []
        context["goal_count"] = sum(len(sec.get("goals") or []) for sec in sections if isinstance(sec, dict))
        context["capture_count"] = self.object.snapshots.count()
        return context


class _OwnedCRUD(CRUDView):
    """Shared rules: list what you may view, edit what you may edit; forms
    stamp the owner (see forms.py)."""

    mixins = [LoginRequiredMixin]
    # "Rows per page" on every list here (15 by default), as on the datasets pages.
    page_sizes = PAGE_SIZE_CHOICES
    displays = [TableDisplay]
    # The tags the rows carry, above the list; one narrows it (?tag=).
    list_accessories = [TagBar()]
    bulk_actions: list = []
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = ("Dashboards", "dashboards_index")
    enable_api = True
    # The switch un-mounts the routes; the tools come from this class, which is
    # imported whatever the switch says.
    enable_mcp = getattr(settings, "SMALLSTACK_DASHBOARDS_ENABLED", True)
    # Each has its own page rather than a CRUD detail, but an agent still has to
    # read one back: get_metric, get_dashboard, get_goal_list…
    mcp_actions = [Action.LIST, Action.DETAIL, Action.CREATE, Action.UPDATE, Action.DELETE]
    mcp_lookup_field = "slug"
    # provided_by: the app that ships the row as a default (blank = made here).
    api_extra_fields = ["visibility", "owner", "created_by", "created_at", "updated_at", "provided_by"]
    api_expand_fields = ["owner", "created_by"]

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        """What the person may open — the active rows, or with ``?archived=1``
        only the archived ones (the way back to something put away)."""
        qs = qs.visible_to(getattr(request, "user", None)).select_related("owner")
        params = request.GET if hasattr(request, "GET") else {}
        qs = qs.tagged(str(params.get("tag") or ""))  # ?tag=ops: the whole tag, as on the overviews
        return qs.archived() if params.get("archived") == "1" else qs.active()

    @classmethod
    def get_detail_queryset(cls, qs: Any, request: HttpRequest) -> Any:
        """One row by its key: archived or not. Archiving takes a row out of
        lists and pickers, never away from a card that draws it, a link that
        reaches it, or the page where it's restored."""
        return qs.visible_to(getattr(request, "user", None)).select_related("owner")

    @classmethod
    def can_update(cls, obj: OwnedModel, request: HttpRequest) -> bool:
        return obj.can_edit(getattr(request, "user", None))

    @classmethod
    def can_delete(cls, obj: OwnedModel, request: HttpRequest) -> bool:
        # A dashboard a page is built on would only be recreated on the next visit.
        if getattr(obj, "system_key", ""):
            return False
        return obj.can_edit(getattr(request, "user", None))

    @classmethod
    def row_link_url(cls, obj: Any, request: HttpRequest) -> str:
        return str(obj.get_absolute_url())

    @classmethod
    def row_actions(cls, obj: Any, request: HttpRequest, default_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The table view's delete opens the same confirmation as the library
        view — the delete mixin answers htmx with the modal fragment."""
        return [{**a, "confirm_modal": f"Delete {obj}?"} if a.get("is_delete") else a for a in default_actions]


def _owner_cell(value: Any, obj: OwnedModel) -> str:
    return "Shared" if obj.owner_id is None else str(obj.owner)


def browse_prefill(params: Any, user: Any) -> dict[str, Any]:
    """What the dataset browser hands over — ``dataset``, ``filter_tree``,
    ``agg``, ``measure`` and maybe a ``name`` — checked and kept as a metric
    form's values: the dataset must be one *user* can read, the tree one it
    can apply, the aggregate and measure ones it has. Anything else is left
    out, never an error. Without a name, the dataset's label and the tree
    read as words. Empty when the dataset isn't usable."""
    from apps.datasets.registry import get_def, user_may_read

    from .metrics import aggs_available

    initial: dict[str, Any] = {}
    key = params.get("dataset", "").strip()
    dfn = get_def(key) if key else None
    if dfn is None or not user_may_read(dfn, user):
        return initial
    ds = get_dataset(key)
    if ds is None:
        return initial
    initial.update({"source": "dataset", "dataset": key})
    tree: Any = None
    try:
        tree = json.loads(params.get("filter_tree", "") or "null")
    except ValueError:
        tree = None
    if isinstance(tree, dict) and tree and not ds.validate_filter_tree(tree):
        initial["filter_tree"] = tree
    agg = params.get("agg", "").strip()
    if agg in dict(aggs_available()):
        initial["agg"] = agg
    measure = params.get("measure", "").strip()
    if measure and measure in set(ds.column_names()):
        initial["measure"] = measure
    name = params.get("name", "").strip()
    if not name:
        labels = {c["name"]: c["label"] for c in ds.schema()["columns"]}
        kept = initial.get("filter_tree")
        reading = describe_filter_tree(kept, labels) if kept else ""
        name = f"{dfn.label}: {reading}" if reading and len(dfn.label) + len(reading) + 2 <= 120 else dfn.label
    initial["name"] = name[:120]
    return initial


def card_handoff(params: Any) -> Optional[dict[str, str]]:
    """``then=card`` with a registered ``card_type`` (and maybe a
    ``dimension``): the card to build once the metric is saved, or None."""
    if params.get("then") != "card":
        return None
    ct = get_component_type(params.get("card_type", "").strip())
    if ct is None:
        return None
    dimension = params.get("dimension", "").strip()
    # Its label for the notice, when the dataset is known; the key rides along as is.
    ds = get_dataset(params.get("dataset", "").strip()) if dimension else None
    label = dimension
    if ds is not None:
        label = next((c["label"] for c in ds.schema()["columns"] if c["name"] == dimension), dimension)
    return {"type": ct.key, "label": ct.label, "dimension": dimension, "dimension_label": label}


def card_builder_url(metric: Metric, then: dict[str, str]) -> str:
    """The component builder opened on *metric* for the card *then* names."""
    params = {"metric": metric.key, "type": then["type"]}
    if then["dimension"]:
        params["dimension"] = then["dimension"]
    return reverse("dashboards/components-create") + "?" + urlencode(params)


class MetricCreateMixin:
    """The full metric form opened from the dataset browser ("Open the full
    form"): ``?dataset=&filter_tree=&agg=&measure=`` prefill it
    (:func:`browse_prefill`), so the metric is the filtered table reduced to
    one number. With ``then=card`` (plus ``card_type`` and ``dimension``) the
    hand-off continues after saving to the component builder, prefilled with
    the new metric — a grouped roll-up becomes a grouped card, through a
    real, named metric rather than a hidden one, so the KPI, the card, a
    goal and the history all share it."""

    request: HttpRequest
    object: Metric

    #: What a duplicate carries over: everything that defines the number, and
    #: the labels. Not the key (made from the new name), the owner (the
    #: person's) or the dates.
    COPIED = METRIC_COPIED

    def get_initial(self) -> dict[str, Any]:
        initial: dict[str, Any] = super().get_initial()  # type: ignore[misc]
        # Duplicate: the form opened with another metric's settings, nothing
        # saved until Save — ``?from=<key>``, any metric the person can see.
        original = Metric.objects.filter(key=self.request.GET.get("from", "").strip()).first()
        if original is not None and original.can_view(self.request.user):
            initial.update({field: getattr(original, field) for field in self.COPIED})
            initial["name"] = f"{original.name} (copy)"[:120]
            initial["visibility"] = "personal"
            # From the dataset browser (started from this metric, conditions maybe
            # changed since): the rows as they are there, over the copy.
            if self.request.GET.get("dataset") == original.dataset:
                handed = browse_prefill(self.request.GET, self.request.user)
                initial["filter_tree"] = handed.get("filter_tree") or {}
                initial.update({k: handed[k] for k in ("agg", "measure") if k in handed})
            return initial
        initial.update(browse_prefill(self.request.GET, self.request.user))
        return initial

    def then_card(self) -> Optional[dict[str, str]]:
        """The card to build after saving, from the query (first visit) or the
        posted hidden fields (the save), or None."""
        return card_handoff(self.request.POST if self.request.method == "POST" else self.request.GET)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        context["then_card"] = self.then_card()
        return context

    def get_success_url(self) -> str:
        then = self.then_card()
        if then is None:
            return str(super().get_success_url())  # type: ignore[misc]
        return card_builder_url(self.object, then)


class MetricQuickView(LoginRequiredMixin, View):
    """**Make a metric** on the dataset browser: the metric form as the global
    modal's body, so several metrics can be made from one filtered table
    without leaving it. GET draws the form from the browser's hand-off
    (:func:`browse_prefill`) beside the value it would produce; the form
    re-draws itself on change (hx-get) so the value is always of what's
    picked. POST saves through ``MetricForm`` — the same validation, key and
    owner rules as the full form — then draws what to do next: open it, make
    a card, add it to goals, make another. ``then=card`` (the roll-up's card
    links) leads to the component builder on the new metric. ``from=<key>``
    (the browser started from a saved metric) makes it a copy: the source's
    thresholds, unit, description and tags come along on save."""

    template_name = "dashboards/partials/metric_quick.html"
    #: What the form carries that the browser's hand-off doesn't.
    OWN_FIELDS = ("period_field", "format", "visibility")

    def get(self, request: HttpRequest) -> HttpResponse:
        values = self.values(request.GET, request.user)
        if not values:
            raise Http404
        return render(request, self.template_name, self.context(request, values, request.GET))

    def post(self, request: HttpRequest) -> HttpResponse:
        from .forms import MetricForm

        values = self.values(request.POST, request.user)
        if not values:
            raise Http404
        source = values.get("source_metric")
        data = {
            **{k: v for k, v in values.items() if k not in ("filter_tree", "from", "source_metric")},
            "filter_tree": json.dumps(values.get("filter_tree") or {}),
            "thresholds": json.dumps(source.thresholds or []) if source else "[]",
            "unit": source.unit if source else "",
            "description": source.description if source else "",
            "name": request.POST.get("name", "").strip(),
        }
        if source is not None:
            data["tags"] = source.tags
        form = MetricForm(data=data, user=request.user)
        if not form.is_valid():
            context = self.context(request, {**values, "name": data["name"]}, request.POST)
            # "__all__" can't be read in a template (a leading underscore); the form's own errors go under "all".
            context["errors"] = {
                ("all" if field == "__all__" else field): [str(e) for e in errs] for field, errs in form.errors.items()
            }
            return render(request, self.template_name, context, status=422)
        metric = form.save()
        context = self.context(request, values, request.POST, preview=False)
        then = context["then"]
        context.update(
            saved=metric,
            saved_result=evaluate(metric, request, period=None),
            card_url=card_builder_url(metric, then) if then else "",
            make_card_url=reverse("dashboards/components-create") + "?" + urlencode({"metric": metric.key}),
        )
        return render(request, self.template_name, context)

    @classmethod
    def values(cls, params: Any, user: Any) -> dict[str, Any]:
        """The form's values from *params*: the browser's hand-off, checked,
        plus the period column (a date column of the dataset, else the first
        one — a period is what makes weeks and goals work), the format and
        the visibility (shared for staff, who build for everyone; the browser
        is theirs)."""
        from .metrics import FORMATS

        values = browse_prefill(params, user)
        if not values:
            return values
        ds = get_dataset(values["dataset"])
        assert ds is not None
        dates = [f["name"] for f in ds.schema().get("filters", []) if f.get("is_date")]
        period_field = params.get("period_field", "").strip()
        if "period_field" in params:
            values["period_field"] = period_field if period_field in dates else ""
        else:
            values["period_field"] = dates[0] if dates else ""
        fmt = params.get("format", "").strip()
        values["format"] = fmt if fmt in dict(FORMATS) else "number"
        visibility = params.get("visibility", "").strip()
        if visibility not in ("shared", "personal"):
            visibility = "shared" if getattr(user, "is_staff", False) else "personal"
        values["visibility"] = visibility
        # A copy of a saved metric on the same dataset, which the person can see.
        key = params.get("from", "").strip()
        source = Metric.objects.filter(key=key, dataset=values["dataset"]).first() if key else None
        if source is not None and source.can_view(user):
            values["from"] = key
            values["source_metric"] = source
        return values

    def context(
        self, request: HttpRequest, values: dict[str, Any], params: Any, *, preview: bool = True
    ) -> dict[str, Any]:
        from .metrics import FORMATS, aggs_available
        from .models import same_metrics
        from .previews import preview_metric

        ds = get_dataset(values["dataset"])
        assert ds is not None
        schema = ds.schema()
        labels = {c["name"]: c["label"] for c in schema["columns"]}
        tree = values.get("filter_tree") or {}
        then = card_handoff(params)
        # The metric's own fields, without the copy's source (not a form value).
        plain = {k: v for k, v in values.items() if k not in ("source_metric", "from")}
        # What's already there: a metric that reads these rows this way (a
        # twin), and the others on this dataset — said before another is saved.
        twins = same_metrics(request.user, values["dataset"], tree, values.get("agg", ""), values.get("measure", ""))
        on_dataset = Metric.objects.visible_to(request.user).filter(source="dataset", dataset=values["dataset"])
        on_dataset = on_dataset.exclude(pk__in=[m.pk for m in twins]).order_by("name")
        # The same hand-off, for the full form and for "make another".
        carried = ("dataset", "filter_tree", "agg", "measure", "then", "card_type", "dimension", "from")
        handoff = {k: params.get(k, "") for k in carried}
        handoff = {k: v for k, v in handoff.items() if v}
        return {
            "values": values,
            "tree_json": json.dumps(tree, separators=(",", ":")) if tree else "",
            "reading": describe_filter_tree(tree, labels) if tree else "",
            "dataset_label": schema.get("label") or values["dataset"],
            "aggs": aggs_available(),
            "formats": FORMATS,
            "measures": [c for c in schema["columns"] if c["role"] == "measure"],
            "date_columns": [f for f in schema.get("filters", []) if f.get("is_date")],
            "then": then,
            "quick_url": reverse("dashboards_metric_quick"),
            "again_url": reverse("dashboards_metric_quick") + "?" + urlencode(handoff),
            "full_url": reverse("dashboards/metrics-create") + "?" + urlencode(handoff),
            "can_share": getattr(request.user, "is_staff", False),
            "copy_of": values.get("source_metric"),
            "twins": twins,
            "on_dataset": list(on_dataset[:3]),
            "on_dataset_count": on_dataset.count(),
            "preview": (
                preview_metric(request.user, {**plain, "name": plain.get("name") or "Preview"}, request=request)
                if preview
                else None
            ),
            "errors": {},
        }


class MetricCRUDView(_OwnedCRUD):
    model = Metric
    form_class = MetricForm
    fields = [
        "name",
        "key",
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
    ]
    list_fields = ["name", "key", "source", "dataset", "agg", "owner", "updated_at"]
    column_labels = {"agg": "Roll-up", "updated_at": "Updated"}
    # Eight columns: the short ones sized so none collapses to "dem…"; the name
    # (the link) gets the framework's default; the table scrolls past its minimum.
    column_widths = {
        "key": "150px",
        "source": "125px",
        "dataset": "160px",
        "agg": "100px",
        "owner": "80px",
        "updated_at": "240px",
    }
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/metrics"
    view_mixins = {Action.CREATE: [MetricCreateMixin], Action.DELETE: [MetricDeleteMixin]}
    displays = [MetricLibraryDisplay, TableDisplay]
    search_fields = ["name", "key", "description", "dataset", "tags"]
    ordering_fields = ["name", "key", "dataset", "updated_at"]
    breadcrumb_parent = ("Goals", "goals_index")
    mcp_singular = "metric"
    mcp_plural = "metrics"
    mcp_lookup_field = "key"
    mcp_description = (
        "a metric: one named number (KPI). source says where it comes from: dataset (default: a stored filter "
        "over a dataset, rolled up), manual (values entered by hand with metric_record_value; agg is "
        "latest|sum|avg|min|max, anything else reads as latest, and dataset, measure, filter_tree and period_field "
        "are set for you) or rate (numerator and denominator are metric keys, divided over the same period; the "
        "percent format multiplies by 100, so a goal's target on it is in percent: 2% is 2). Fields: key (stable "
        "slug), name, source, numerator, denominator, "
        "dataset (a dataset key — see "
        "list_datasets / describe_dataset), filter_tree (nested "
        'AND/OR JSON: {"and": [{"field", "op", "value"}]}; ops: = != > >= < <= between in contains isnull '
        "period), agg (count|distinct|sum|avg|min|max), measure (column for non-count aggs), period_field "
        "(date column a dashboard period narrows), format (number|compact|decimal|percent|currency|duration: "
        "duration reads the value as seconds), "
        'unit, thresholds ([{"op": ">=", "value": 10, "state": "danger"}]), visibility (personal|shared). '
        "Dry-run with metric_preview before creating"
    )

    @classmethod
    def on_delete(cls, request: Any, obj: Metric) -> None:
        """Remove the metric's dashboard cards and report rows before it goes,
        so nothing is left showing "metric no longer exists". Runs on every
        delete surface, in the delete's transaction. The delete page's checkbox
        is the one opt-out: its form carries ``detach_choice`` so an unticked
        box means "keep them"; REST, MCP and bulk deletes always clean up."""
        from .models import detach_metric

        post = getattr(request, "POST", None)
        if post is not None and post.get("detach_choice") and post.get("detach") != "1":
            return
        user = getattr(request, "user", None)
        usage = metric_usage(obj, user)
        request._dashboards_detached = detach_metric(obj, user)
        # MCP's delete answers with this: it has no confirmation page.
        request.delete_effects = {
            "cards": request._dashboards_detached[0],
            "report_rows_and_goals": request._dashboards_detached[1],
            "dashboards": [x["obj"].name for x in usage["boards"] if x["can_edit"]],
            "reports": [x["obj"].name for x in usage["reports"] if x["can_edit"]],
            "goal_lists": [x["obj"].name for x in usage["goal_lists"] if x["can_edit"]],
            "saved_cards": [c.key for c in usage["components"] if c.can_edit(user)],
            "rates_left_without_it": [m.key for m in usage["rates"]],
            "still_broken_in": [
                x["obj"].name for x in usage["boards"] + usage["reports"] + usage["goal_lists"] if not x["can_edit"]
            ],
        }


def _free_slug(model: type[Any], name: str) -> str:
    """A slug for a duplicate — the name slugified, ``-2``, ``-3``… until it's
    free — so the copy's address never collides with the original's."""
    return free_slug(model, name)


class _DuplicateMixin:
    """Duplicate for the slug-keyed types: ``?from=<slug>`` opens the create
    form with the original's settings — its defining fields and tags, the
    name "(copy)", a free slug, visibility personal — and nothing is saved
    until Save. Subclasses name the model and the fields carried over."""

    request: HttpRequest
    duplicate_model: type[Any]
    duplicate_fields: tuple[str, ...]

    def get_initial(self) -> dict[str, Any]:
        initial: dict[str, Any] = super().get_initial()  # type: ignore[misc]
        slug = self.request.GET.get("from", "").strip()
        original = self.duplicate_model.objects.filter(slug=slug).first() if slug else None
        if original is None or not original.can_view(self.request.user):
            return initial
        initial.update({field: getattr(original, field) for field in self.duplicate_fields})
        name = f"{original.name} (copy)"[:120]
        initial.update(name=name, slug=_free_slug(self.duplicate_model, name), visibility="personal")
        return initial


class DashboardDuplicateMixin(_DuplicateMixin):
    duplicate_model = Dashboard
    duplicate_fields = ("description", "default_period", "refresh_seconds", "layout", "tags")

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        if initial.get("layout"):
            initial["layout"], changed, dropped = _layout_for(self.request.user, initial["layout"])
            if changed or dropped:
                said = []
                if changed:
                    said.append(f"{changed} card(s) over someone else's personal metric now filter its data themselves")
                if dropped:
                    said.append(f"{dropped} card(s) over a metric you can't use were left out")
                messages.info(self.request, "; ".join(said) + ".")
        return initial


def _layout_for(user: Any, layout: list[Any]) -> tuple[list[Any], int, int]:
    """A copy of *layout* that *user* can save as their own: a card over
    another user's personal metric (which a copy may not place) filters that
    metric's dataset itself, or is left out when the metric has no dataset
    to filter (entered by hand, a rate). The Duplicate dialog offered a copy
    that then failed on save. Returns ``(layout, changed, dropped)``."""
    keys = {c.get("metric") for c in layout if isinstance(c, dict) and isinstance(c.get("metric"), str)}
    theirs = {
        m.key: m
        for m in Metric.objects.filter(key__in=keys).exclude(owner_id=None).exclude(owner_id=getattr(user, "pk", None))
    }
    out, changed, dropped = [], 0, 0
    for cell in layout:
        metric = theirs.get(str(cell.get("metric") or "")) if isinstance(cell, dict) else None
        if metric is None:
            out.append(cell)
        elif metric.is_manual or metric.is_rate:
            dropped += 1
        else:
            options = dict(cell.get("options") or {})
            options.setdefault("style", {"format": metric.format, "unit": metric.unit})
            if metric.thresholds:
                options.setdefault("thresholds", metric.thresholds)
            own = {k: v for k, v in cell.items() if k != "metric"}
            own.update(
                dataset=metric.dataset,
                filter_tree=metric.filter_tree or {},
                agg=metric.agg or "count",
                measure=metric.measure,
                period_field=metric.period_field,
                options=options,
                title=cell.get("title") or metric.name,
            )
            out.append(own)
            changed += 1
    return out, changed, dropped


class ReportDuplicateMixin(_DuplicateMixin):
    duplicate_model = Report
    duplicate_fields = ("description", "items", "periods", "tags")


class PlaylistDuplicateMixin(_DuplicateMixin):
    duplicate_model = Playlist
    duplicate_fields = ("description", "items", "seconds", "loop", "auto_start", "tags")


class GoalListDuplicateMixin(_DuplicateMixin):
    duplicate_model = GoalList
    duplicate_fields = ("description", "default_period", "sections", "tags")


class DashboardCRUDView(_OwnedCRUD):
    model = Dashboard
    form_class = DashboardForm
    fields = [
        "name",
        "slug",
        "description",
        "cover_image",
        "cover_alt",
        "default_period",
        "refresh_seconds",
        "layout",
        "tags",
    ]
    list_fields = ["name", "slug", "default_period", "owner", "updated_at"]
    column_labels = {"default_period": "Opens with", "updated_at": "Updated"}
    column_widths = {"default_period": "130px", "owner": "140px"}
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/boards"
    api_extra_fields = [*_OwnedCRUD.api_extra_fields, "sharing"]  # who a personal dashboard is shared with
    view_mixins = {Action.CREATE: [DashboardDuplicateMixin], Action.DELETE: [DashboardDeleteMixin]}
    displays = [DashboardLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description", "tags"]
    ordering_fields = ["name", "slug", "updated_at"]
    mcp_singular = "dashboard"
    mcp_plural = "dashboards"
    mcp_description = (
        "a dashboard: a grid of cards. layout is a list of cells on a 12-column grid — "
        '{"id", "type", "x", "y", "w", "h", "title"?, "options"?, "use_period"?} plus one source: a dataset '
        "the card filters itself (dataset + filter_tree + agg/measure + period_field, any design), metric = a "
        "saved metric's key (single-value designs only: metric, gauge; a hand-entered or rate metric also on a "
        "design that doesn't split into groups, e.g. trend), or component = a saved card's key. Types from "
        "list_dashboard_components (metric_group needs options.dimension, text options.markdown, widget "
        "options.widget). default_period = a period key or blank; visibility = personal|shared. "
        "cover_image is the dashboard's picture: read-only here (its URL), uploaded as multipart over REST. "
        "dashboard_add_card appends one card without rewriting the layout"
    )


class ReportCRUDView(_OwnedCRUD):
    model = Report
    form_class = ReportForm
    fields = ["name", "slug", "description", "items", "periods", "tags"]
    list_fields = ["name", "slug", "periods", "owner", "updated_at"]
    column_labels = {"updated_at": "Updated"}
    column_widths = {"owner": "140px"}
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/reports"
    view_mixins = {Action.CREATE: [ReportDuplicateMixin], Action.DELETE: [ReportDeleteMixin]}
    displays = [ReportLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description", "tags"]
    ordering_fields = ["name", "slug", "updated_at"]
    breadcrumb_parent = ("Goals", "goals_index")
    mcp_singular = "report"
    mcp_plural = "reports"
    mcp_description = (
        'a KPI report: items = ordered rows [{"metric": "<key>", "label"?: "..."}], periods = column '
        'period keys (["mtd", "pmtd", "ytd"]; empty = one All-time column); visibility = personal|shared. '
        "report_values evaluates it"
    )


class PlaylistCRUDView(_OwnedCRUD):
    model = Playlist
    form_class = PlaylistForm
    view_mixins = {Action.CREATE: [PlaylistDuplicateMixin], Action.DELETE: [PlaylistDeleteMixin]}
    fields = ["name", "slug", "description", "items", "seconds", "loop", "auto_start", "tags"]
    list_fields = ["name", "slug", "seconds", "owner", "updated_at"]
    column_labels = {"seconds": "Seconds", "updated_at": "Updated"}
    column_widths = {"seconds": "120px", "owner": "140px"}
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/playlists"
    displays = [PlaylistLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description", "tags"]
    ordering_fields = ["name", "slug", "seconds", "updated_at"]
    breadcrumb_parent = ("Dashboards", "dashboards_index")
    mcp_singular = "playlist"
    mcp_plural = "playlists"
    mcp_description = (
        'a playlist: items = slides in order: {"dashboard": "<slug>"} or {"goals": "<goal list slug>", '
        '"show"?: "now"|"week"|"weeks"} (the goals now, the week just ended, or week over week), each with '
        '"seconds"?: 5-3600, '
        '"period"?: "<key>"|"all" (a bare slug is a dashboard); seconds = default time on each; loop; '
        "auto_start = play as soon as it opens; visibility = personal|shared (a shared playlist holds only "
        "shared slides). Open it at url; ?slide=N&play=1&seconds=N&loop=0&kiosk=1 control the player. "
        "playlist_slides shows what a viewer gets"
    )


class PlaylistPlayerView(LoginRequiredMixin, TemplateView):
    """``/smallstack/dashboards/p/<slug>/`` — the playlist, playing. Its link
    options (``?slide=&play=&seconds=&loop=&kiosk=``) are read by
    ``playlists.player_options``; the address bar follows the current slide,
    so a copied link resumes where it was."""

    template_name = "dashboards/playlist.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        playlist = visible_or_404(Playlist.objects.all(), self.request, slug=kwargs["slug"])
        context.update(player_context(playlist, self.request, sync_url=True))
        context["can_edit"] = playlist.can_edit(self.request.user)
        return context


class PlaylistSlideView(LoginRequiredMixin, View):
    """One slide's markup (the dashboard, laid out as ``{% dashboard %}``
    lays it out) — what the player fetches as it pages. ``position`` is
    1-based, as in ``?slide=``."""

    def get(self, request: HttpRequest, slug: str, position: int) -> HttpResponse:
        playlist = visible_or_404(Playlist.objects.all(), request, slug=slug)
        slides = playlist_slides(playlist, request.user)
        if not 1 <= position <= len(slides):
            raise Http404
        slide = slides[position - 1]
        return render(
            request,
            "dashboards/partials/playlist_slide.html",
            {"slide": slide, "embed": slide_embed(slide, request), "count": len(slides)},
        )


class _GoalListSavedMixin:
    """Saving goals lands on the list you were arranging, not the list of lists."""

    def get_success_url(self) -> str:
        return str(self.object.get_absolute_url())  # type: ignore[attr-defined]


class GoalListCRUDView(_OwnedCRUD):
    """Goal lists — the goals editor is this view's form page; the list's own
    page (the meeting view) is :class:`GoalListPageView`."""

    model = GoalList
    form_class = GoalListForm
    fields = ["name", "slug", "description", "default_period", "sections", "tags"]
    list_fields = ["name", "slug", "default_period", "owner", "updated_at"]
    column_labels = {"default_period": "Opens with", "updated_at": "Updated"}
    column_widths = {"default_period": "130px", "owner": "140px"}
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/goals"
    view_mixins = {
        Action.CREATE: [GoalListDuplicateMixin, _GoalListSavedMixin],
        Action.UPDATE: [_GoalListSavedMixin],
        Action.DELETE: [GoalListDeleteMixin],
    }
    displays = [GoalListLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description", "tags"]
    ordering_fields = ["name", "slug", "default_period", "updated_at"]
    breadcrumb_parent = ("Goals", "goals_index")
    mcp_singular = "goal_list"
    mcp_plural = "goal_lists"
    mcp_description = (
        'a goal list: sections = [{"title": "Support", "goals": [goal, ...]}], each goal = {"metric": "<key>" '
        'or "component": "<single-stat card key>", "target": {"op": ">=", "value": 95}, "warn"?: {"op", '
        '"value"} (the at-risk line, an easier target pointing the same way: "under 1, at risk up to 2" is target '
        '< 1, warn < 2), "targets"?: {"hourly": {"target": rule, "warn"?: rule}} (its own target at a cadence), '
        '"label"?, "period"?: "<key>"|"all", "note"?}; ops: > >= < <= = != '
        "between (value [low, high]). A goal is on target when its value meets target, at risk when it meets "
        "only warn, else missed. Captures and the Weeks and History pages judge against targets for their "
        "cadence; without one, weekly and any number on the same scale at every length (an average, a rate, a "
        "latest reading) use target, and a count or sum isn't judged. default_period = what goals without their "
        "own period are judged "
        "over (blank "
        "= all time); visibility = personal|shared. goal_list_values evaluates it; goal_list_add_goal appends one. "
        "To change or remove a goal: get_goal_list, edit sections, send them all to update_goal_list (goal ids "
        "keep each goal's identity). goal_list_save_week keeps a week as it was"
    )


class GoalListPageView(LoginRequiredMixin, TemplateView):
    """``/smallstack/dashboards/g/<slug>/`` — the meeting view: a summary of
    how many goals are on target and which need attention, then each section's
    goals read down, value against target. ``?period=`` judges them over
    another period; ``?present=1`` drops the site's chrome for a shared screen."""

    template_name = "dashboards/goals.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
        period = requested_period(request, goal_list.default_period)
        data = evaluate_goals(goal_list, request, period=period, trend=True)
        order = goal_order(request.GET.get("order"))
        data["sections"] = sort_sections(data["sections"], order)
        context.update(
            {
                "order": order,
                "sort_links": goal_sort_links(order),
                "swap": "#gl-page",
                "goal_list": goal_list,
                "period": period or "all",
                "heading": period_heading(period),
                **period_nav(period),
                **data,
                "present": request.GET.get("present") == "1",
                "can_edit": goal_list.can_edit(request.user),
                "own_periods": any(r["own_period"] for r in data["rows"]),
                "api_url": request.build_absolute_uri(
                    reverse("dashboards_api_goal_values", kwargs={"slug": goal_list.slug})
                ),
            }
        )
        return context


class GoalListPrintView(LoginRequiredMixin, TemplateView):
    """``g/<slug>/print/`` — the list as a document for paper: the summary, what
    needs attention, then each section's goals. ``?period=`` and ``?order=`` follow
    the meeting view; ``?week=`` prints that week instead, saved values included.
    ``?auto=1`` opens the print dialog on arrival."""

    template_name = "dashboards/print/goal_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from .snapshots import Period
        from .weeks import _masked, _sections, parse_week, week_page

        context = super().get_context_data(**kwargs)
        request = self.request
        goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
        week = parse_week(request.GET.get("week"))
        order = goal_order(request.GET.get("order"))
        wanted = request.GET.get("snapshot", "")
        capture = goal_list.snapshots.filter(pk=wanted).first() if wanted.isdigit() else None
        if capture is not None:
            rows = _masked(capture.rows, request.user)
            captured = Period(capture.cadence, capture.period_start, capture.period_end)
            data: dict[str, Any] = {
                "sections": _sections(rows),
                "rows": rows,
                "summary": summarize(rows),
                "attention": [r for r in rows if r["status"] in ("fail", "warn")],
            }
            back = reverse("dashboards_goal_history", kwargs={"slug": goal_list.slug})
            back += f"?cadence={capture.cadence}&at={captured.key}"
            when = f"{captured.label}, as captured {capture.taken_at:%b} {capture.taken_at.day}"
        elif week is not None:
            page = week_page(goal_list, request, week)
            data = {k: page[k] for k in ("sections", "rows", "summary", "attention")}
            back = f"{reverse('dashboards_goal_weeks', kwargs={'slug': goal_list.slug})}?week={week.isoformat()}"
            when = f"Week of {page['label']}"
        else:
            period = requested_period(request, goal_list.default_period)
            data = evaluate_goals(goal_list, request, period=period)
            back = goal_list.get_absolute_url()
            when = period_heading(period)
        data["sections"] = sort_sections(data["sections"], order)
        context.update(
            {
                "goal_list": goal_list,
                "document_title": goal_list.name,
                "document_description": goal_list.description,
                "when": when,
                "back_url": back,
                "has_changes": any(r.get("comparison") for r in data["rows"]),
                "printed_at": timezone.localtime(),
                "auto_print": request.GET.get("auto") == "1",
                **data,
            }
        )
        return context


class ReportPrintView(LoginRequiredMixin, TemplateView):
    """``r/<slug>/print/`` — the report as a document for paper. ``?order=`` follows
    the page; ``?auto=1`` opens the print dialog on arrival."""

    template_name = "dashboards/print/report.html"
    #: Past this many period columns the table needs a sideways page.
    PORTRAIT_COLUMNS = 3

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        report = visible_or_404(Report.objects.all(), request, slug=kwargs["slug"])
        matrix = report_matrix(report, request)
        matrix = sort_report(matrix, report_order(request.GET.get("order"), matrix))
        presented = present_report(matrix)
        context.update(
            {
                "report": report,
                "matrix": presented,
                "document_title": report.name,
                "document_description": report.description,
                "back_url": report.get_absolute_url(),
                "landscape": len(presented["columns"]) > self.PORTRAIT_COLUMNS,
                "printed_at": timezone.localtime(),
                "auto_print": request.GET.get("auto") == "1",
            }
        )
        return context


class GoalWeeksView(LoginRequiredMixin, TemplateView):
    """``g/<slug>/weeks/`` — a goal list week by week, the spreadsheet with a
    tab per week. ``?week=`` (any day of it, or ``2026-W45``) picks the week,
    arrows move between weeks; ``?view=grid`` lays goals down and weeks across
    (``?format=csv`` downloads that). A week with a snapshot shows it as it
    was; the rest are worked out now (``weeks.py``)."""

    template_name = "dashboards/goal_weeks.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.GET.get("format") == "csv":
            from .weeks import grid_order, sort_grid, week_grid, write_grid_csv

            goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
            grid = week_grid(goal_list, request, self.chosen_week(request))
            grid = sort_grid(grid, grid_order(request.GET.get("order"), grid))
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{goal_list.slug}-weeks.csv"'
            write_grid_csv(grid, response)
            return response
        return super().get(request, *args, **kwargs)

    @staticmethod
    def chosen_week(request: HttpRequest) -> Any:
        from .weeks import parse_week, this_week

        chosen = parse_week(request.GET.get("week")) or this_week()
        return min(chosen, this_week())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from .weeks import grid_order, grid_sort_links, sort_grid, week_choices, week_grid, week_page

        context = super().get_context_data(**kwargs)
        request = self.request
        goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
        start = self.chosen_week(request)
        view = "grid" if request.GET.get("view") == "grid" else "week"
        context.update(
            {
                "goal_list": goal_list,
                "view": view,
                "start": start,
                "choices": week_choices(goal_list, start),
                "can_edit": goal_list.can_edit(request.user),
                "weekly_tracked": goal_list.trackers.filter(cadence="weekly").exists(),
                "snapshot_count": goal_list.snapshots.filter(cadence="weekly")
                .order_by()
                .values("period_start")
                .distinct()
                .count(),
            }
        )
        if view == "grid":
            grid = week_grid(goal_list, request, start)
            order = grid_order(request.GET.get("order"), grid)
            context["grid"] = sort_grid(grid, order)
            context["order"] = order
            links = grid_sort_links(grid, order)
            context["sort_links"] = links
            for col in grid["columns"]:
                col["sort"] = links[f"w{col['start'].isoformat()}"]
        else:
            week = week_page(goal_list, request, start)
            order = goal_order(request.GET.get("order"))
            week["sections"] = sort_sections(week["sections"], order)
            context.update(week=week, order=order, sort_links=goal_sort_links(order), swap="#gw-page")
        return context


SNAPSHOT_NOUNS = {"hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month", "quarterly": "quarter"}


class GoalHistoryView(LoginRequiredMixin, TemplateView):
    """``g/<slug>/history/`` — the list's captures. Which cadences are tracked (editors
    change them here), then goals down and periods across for one cadence
    (``?cadence=``, ``?last=`` the newest column, ``?format=csv``). ``?at=<period>`` opens
    one period with every capture of it, ``&capture=<id>`` picks an earlier one."""

    template_name = "dashboards/goal_history.html"

    @staticmethod
    def cadence_from(request: HttpRequest, goal_list: GoalList) -> str:
        from .snapshots import DAILY, tracked_cadences

        asked = request.GET.get("cadence", "")
        if asked in dict(SNAPSHOT_CADENCES):
            return asked
        tracked = tracked_cadences(goal_list)
        return tracked[0] if tracked else DAILY

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if request.GET.get("format") == "csv":
            from .snapshots import history_grid, parse_period
            from .weeks import grid_order, sort_grid, write_grid_csv

            goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
            cadence = self.cadence_from(request, goal_list)
            grid = history_grid(goal_list, request, cadence, parse_period(cadence, request.GET.get("last")))
            grid = sort_grid(grid, grid_order(request.GET.get("order"), grid))
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{goal_list.slug}-{cadence}.csv"'
            write_grid_csv(grid, response)
            return response
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from .snapshots import MAX_FILL, captures_of, history_grid, parse_period, tracked_cadences
        from .weeks import _masked, _sections, grid_order, grid_sort_links, sort_grid

        context = super().get_context_data(**kwargs)
        request = self.request
        goal_list = visible_or_404(GoalList.objects.all(), request, slug=kwargs["slug"])
        cadence = self.cadence_from(request, goal_list)
        tracked = tracked_cadences(goal_list)
        grid = history_grid(goal_list, request, cadence, parse_period(cadence, request.GET.get("last")))
        order = grid_order(request.GET.get("order"), grid)
        links = grid_sort_links(grid, order)
        for column in grid["columns"]:
            column["sort"] = links[f"w{column['start'].isoformat()}"]
        context.update(
            {
                "goal_list": goal_list,
                "cadence": cadence,
                "cadence_noun": SNAPSHOT_NOUNS[cadence],
                "tabs": [
                    {"key": k, "label": label, "tracked": k in tracked}
                    for k, label in SNAPSHOT_CADENCES
                ],
                "tracked": tracked,
                "grid": sort_grid(grid, order),
                "order": order,
                "sort_links": links,
                "fill_choices": [n for n in (4, 8, 12, 24, 48) if n <= MAX_FILL[cadence]],
                "can_edit": goal_list.can_edit(request.user),
            }
        )
        period = parse_period(cadence, request.GET.get("at"))
        if period is not None:
            captures = captures_of(goal_list, period)
            chosen = next((c for c in captures if str(c.pk) == request.GET.get("capture")), None)
            chosen = chosen or (captures[0] if captures else None)
            rows = []
            if chosen is not None:
                rows = [
                    r | {"comparison": None, "drill": None}
                    for r in _masked(chosen.rows, request.user)
                ]
            summary = summarize(rows)
            context.update(
                {
                    "period": period,
                    "captures": captures,
                    "chosen": chosen,
                    "detail_rows": rows,
                    "detail_sections": _sections(rows),
                    "detail_summary": summary,
                    "detail_attention": [r for r in rows if r["status"] in ("fail", "warn")],
                }
            )
        return context


class GoalTrackingView(LoginRequiredMixin, View):
    """POST ``cadence=`` (repeated): exactly the cadences this list tracks. Editors only."""

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        from .snapshots import set_tracking

        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        if not goal_list.can_edit(request.user):
            raise PermissionDenied
        try:
            tracked = set_tracking(goal_list, request.POST.getlist("cadence"), by=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            words = ", ".join(tracked) if tracked else "nothing"
            messages.success(request, f"Now tracking: {words}. What's already captured stays.")
        return redirect(reverse("dashboards_goal_history", kwargs={"slug": slug}))


class GoalCaptureView(LoginRequiredMixin, View):
    """POST ``cadence=``: capture the current period now. With ``fill=<n>``, capture
    the past *n* periods that have none. Editors only."""

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        from .snapshots import capture, current_period, fill

        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        if not goal_list.can_edit(request.user):
            raise PermissionDenied
        cadence = request.POST.get("cadence", "")
        if cadence not in dict(SNAPSHOT_CADENCES):
            raise Http404("Unknown cadence.")
        if request.POST.get("fill"):
            try:
                done = fill(goal_list, cadence, int(request.POST["fill"]), by=request.user)
            except ValueError:
                raise Http404("Not a number of periods.") from None
            noun = SNAPSHOT_NOUNS[cadence]
            if done:
                messages.success(request, f"Captured {done} past {noun}{pluralize(done)}.")
            else:
                messages.info(request, f"Those {noun}s already have captures.")
        else:
            period = current_period(cadence)
            capture(goal_list, period, by=request.user)
            messages.success(request, f"Captured {period.label} so far.")
        return redirect(f"{reverse('dashboards_goal_history', kwargs={'slug': slug})}?cadence={cadence}")


class GoalWeekTrendsView(LoginRequiredMixin, View):
    """The trend button on a week: the weeks around it, per goal — a small
    bar per week, this week's value against the week before and the average
    of the weeks before, the run it's on. The global modal's body over htmx;
    a page of its own without."""

    def get(self, request: HttpRequest, slug: str, week: str) -> HttpResponse:
        from .weeks import parse_week, sort_trends, this_week, trends_order, trends_sort_links, week_trends

        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        start = parse_week(week)
        if start is None or start > this_week():
            raise Http404
        template = (
            "dashboards/partials/goal_week_trends.html"
            if request.headers.get("HX-Request")
            else "dashboards/goal_week_trends.html"
        )
        order = trends_order(request.GET.get("order"))
        return render(
            request,
            template,
            {
                "goal_list": goal_list,
                "trends": sort_trends(week_trends(goal_list, request, start), order),
                "order": order,
                "sort_links": trends_sort_links(order),
                "trends_url": request.path,
            },
        )


class GoalWeeksTrendView(LoginRequiredMixin, View):
    """The Trends button on a grid row: one goal over the weeks up to
    ``?week=`` (this week without), a bar per week with its value, the
    change against the week before and the average before, the run, and
    each week in a table. The global modal's body over htmx; a page of its
    own without."""

    def get(self, request: HttpRequest, slug: str, goal_id: str) -> HttpResponse:
        from .weeks import goal_weeks_trend, parse_week, this_week

        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        last = parse_week(request.GET.get("week")) or this_week()
        trend = goal_weeks_trend(goal_list, request, goal_id, last)
        if trend is None:
            raise Http404
        template = (
            "dashboards/partials/goal_weeks_trend.html"
            if request.headers.get("HX-Request")
            else "dashboards/goal_weeks_trend.html"
        )
        return render(request, template, {"goal_list": goal_list, "trend": trend})


#: What the archive button can put away, by the word in its URL.
ARCHIVABLE: dict[str, type[OwnedModel]] = {
    "metric": Metric,
    "dashboard": Dashboard,
    "component": Component,
    "playlist": Playlist,
    "report": Report,
    "goals": GoalList,
}


#: Each owned kind in a confirmation: the word for it, its overview (the page
#: crumb) and the create form a Duplicate opens with ``?from=<key or slug>``.
CONFIRM_KINDS: dict[str, dict[str, str]] = {
    "metric": {"word": "metric", "section": "Goals", "home": "goals_index", "create": "dashboards/metrics-create"},
    "dashboard": {
        "word": "dashboard",
        "section": "Dashboards",
        "home": "dashboards_index",
        "create": "dashboards/boards-create",
    },
    "component": {
        "word": "card",
        "section": "Dashboards",
        "home": "dashboards_index",
        "create": "dashboards/components-create",
    },
    "playlist": {
        "word": "playlist",
        "section": "Dashboards",
        "home": "dashboards_index",
        "create": "dashboards/playlists-create",
    },
    "report": {"word": "report", "section": "Goals", "home": "goals_index", "create": "dashboards/reports-create"},
    "goals": {"word": "goal list", "section": "Goals", "home": "goals_index", "create": "dashboards/goals-create"},
}


def where_used(kind: str, obj: Any, user: Any) -> list[str]:
    """The names of what the person can see that still uses *obj*: what an
    archive keeps working and a delete would change."""
    from .signals import _shows_goal_list

    boards = Dashboard.objects.visible_to(user).active()
    if kind == "metric":
        usage = metric_usage(obj, user)
        return [x["obj"].name for x in usage["boards"] + usage["reports"] + usage["goal_lists"]] + [
            c.name for c in usage["components"]
        ]
    if kind == "component":
        names = [d.name for d in boards if any(isinstance(c, dict) and c.get("component") == obj.key for c in d.layout)]
        return names + [
            g.name
            for g in GoalList.objects.visible_to(user).active()
            if any(
                isinstance(goal, dict) and goal.get("component") == obj.key
                for sec in g.sections
                if isinstance(sec, dict)
                for goal in sec.get("goals") or []
            )
        ]
    playlists = Playlist.objects.visible_to(user).active()
    if kind == "goals":
        names = [d.name for d in boards if any(_shows_goal_list(c, obj.slug) for c in d.layout)]
        return names + [p.name for p in playlists if _plays(p, "goals", obj.slug)]
    if kind == "dashboard":
        return [p.name for p in playlists if _plays(p, "dashboard", obj.slug)]
    return []


def _plays(playlist: Playlist, kind: str, slug: str) -> bool:
    return any(isinstance(i, dict) and i.get(kind) == slug for i in playlist.items or [])


def confirm_context(kind: str, obj: Any, user: Any, action: str) -> dict[str, Any]:
    """What every confirmation page and modal here reads: the kind in words,
    the crumb, and what still uses the row."""
    info = CONFIRM_KINDS[kind]
    return {
        "kind": kind,
        "word": info["word"],
        "section": info["section"],
        "section_url": reverse(info["home"]),
        "action": action,
        "used_in": where_used(kind, obj, user),
        "object": obj,
    }


def _confirm_render(request: HttpRequest, body: str, context: dict[str, Any]) -> HttpResponse:
    """A confirmation in the global modal (htmx), or as a page of its own."""
    context["body_template"] = body
    page = "smallstack_dashboards/crud/owned_confirm_modal.html"
    if not request.headers.get("HX-Request"):
        page = "smallstack_dashboards/crud/owned_confirm_page.html"
    return render(request, page, context)


def _safe_next(request: HttpRequest, raw: str, obj: Any) -> str:
    from django.utils.http import url_has_allowed_host_and_scheme

    hosts = {request.get_host()}
    if raw and url_has_allowed_host_and_scheme(raw, allowed_hosts=hosts, require_https=request.is_secure()):
        return raw
    return obj.get_absolute_url() if hasattr(obj, "get_absolute_url") else reverse("dashboards_index")


class ArchiveToggleView(LoginRequiredMixin, View):
    """GET ``archive/<kind>/<pk>/``: the confirmation, saying what archiving
    means (the modal over htmx, else a page). POST: archive the row, or with
    ``restore=1`` bring it back. Editors only. An archived row leaves every
    list and picker but is still drawn wherever it's referred to, so nothing
    breaks and nothing is lost. Back to ``next`` (on this site) or the row's page."""

    def _editable(self, request: HttpRequest, kind: str, pk: int) -> Any:
        model = ARCHIVABLE.get(kind)
        if model is None:
            raise Http404
        obj = get_object_or_404(model, pk=pk)
        if not obj.can_edit(request.user):
            raise Http404
        return obj

    def get(self, request: HttpRequest, kind: str, pk: int) -> HttpResponse:
        obj = self._editable(request, kind, pk)
        context = confirm_context(kind, obj, request.user, "Archive")
        context["next"] = _safe_next(request, request.GET.get("next", ""), obj)
        return _confirm_render(request, "dashboards/partials/archive_confirm.html", context)

    def post(self, request: HttpRequest, kind: str, pk: int) -> HttpResponse:
        obj = self._editable(request, kind, pk)
        restore = request.POST.get("restore") == "1"
        obj.set_archived(not restore)
        name = getattr(obj, "name", str(obj))
        messages.success(request, f"Restored {name}." if restore else f"Archived {name}. It stays wherever it's used.")
        return redirect(_safe_next(request, request.POST.get("next", ""), obj))


class DefaultResetView(ArchiveToggleView):
    """``defaults/reset/<kind>/<pk>/``: put a default an app ships back as the
    app ships it now (``defaults.reset_default``). GET is the confirmation (the
    modal over htmx, else a page); POST resets. Editors only, like archiving."""

    def get(self, request: HttpRequest, kind: str, pk: int) -> HttpResponse:
        from .defaults import default_state

        obj = self._editable(request, kind, pk)
        state = default_state(obj)
        if state is None or not state["shipped"]:
            raise Http404
        context = confirm_context(kind, obj, request.user, "Reset")
        context.update(state=state, next=_safe_next(request, request.GET.get("next", ""), obj))
        return _confirm_render(request, "dashboards/partials/reset_confirm.html", context)

    def post(self, request: HttpRequest, kind: str, pk: int) -> HttpResponse:
        from django.core.exceptions import ValidationError

        from .defaults import reset_default

        obj = self._editable(request, kind, pk)
        try:
            reset_default(obj)
        except LookupError:
            raise Http404 from None
        except ValidationError as exc:
            messages.error(request, f"{obj.name} couldn't be reset: {' '.join(exc.messages)}")
        else:
            messages.success(request, f"{obj.name} is back to its default.")
        return redirect(_safe_next(request, request.POST.get("next", ""), obj))


class DuplicateConfirmView(LoginRequiredMixin, View):
    """GET ``duplicate/<kind>/<pk>/``: what a Duplicate does, before the form
    opens (the modal over htmx, else a page). Anyone who can see the row may
    duplicate it; the confirmation's button opens the create form with
    ``?from=``, and nothing is saved until that form is."""

    def get(self, request: HttpRequest, kind: str, pk: int) -> HttpResponse:
        model = ARCHIVABLE.get(kind)
        if model is None:
            raise Http404
        obj: Any = get_object_or_404(model, pk=pk)
        if not obj.can_view(request.user):
            raise Http404
        context = confirm_context(kind, obj, request.user, "Duplicate")
        handle = obj.key if kind in ("metric", "component") else obj.slug
        context["form_url"] = f"{reverse(CONFIRM_KINDS[kind]['create'])}?{urlencode({'from': handle})}"
        context["copy_name"] = f"{obj.name} (copy)"[:120]
        return _confirm_render(request, "dashboards/partials/duplicate_confirm.html", context)


class GoalWeekSnapshotView(LoginRequiredMixin, View):
    """POST: take (or retake) the week's snapshot — or, with ``fill=<n>``,
    snapshot the past *n* weeks that don't have one. Needs edit rights on
    the list; back to the week afterwards."""

    def post(self, request: HttpRequest, slug: str, week: str) -> HttpResponse:
        from .weeks import backfill, parse_week, take_snapshot, week_label

        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        if not goal_list.can_edit(request.user):
            raise Http404
        start = parse_week(week)
        if start is None:
            raise Http404
        back = f"{reverse('dashboards_goal_weeks', kwargs={'slug': slug})}?week={start.isoformat()}"
        if request.POST.get("view") == "grid":
            back += "&view=grid"
        if request.POST.get("fill"):
            try:
                n = int(request.POST["fill"])
            except ValueError:
                n = 8
            done = backfill(goal_list, n, by=request.user)
            messages.success(
                request,
                f"Saved {done} past week{'s' if done != 1 else ''}." if done else "Those weeks already have snapshots.",
            )
            return redirect(back)
        try:
            take_snapshot(goal_list, start, by=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Saved the week of {week_label(start)}.")
        return redirect(back)


class GoalListDigestView(LoginRequiredMixin, View):
    """A goal list's summary line and bar (``7 of 9 on target``), loaded
    lazily per row on the lists and the index."""

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        goal_list = visible_or_404(GoalList.objects.all(), request, slug=slug)
        period = requested_period(request, goal_list.default_period)
        rows = evaluate_goals(goal_list, request, period=period, compare=False)["rows"]
        return render(request, "dashboards/partials/goals_digest.html", {"summary": summarize(rows)})


class AddGoalView(LoginRequiredMixin, View):
    """The "Add to goals" dialog for a metric (``?metric=<key>``) or a single-stat card
    (``?component=<key>``): pick a goal list you may edit and a section, set
    the target. Over htmx it's the global modal's body and answers with a
    confirmation; without, an ordinary page that redirects to the list."""

    template_name = "dashboards/goal_add.html"
    partial_name = "dashboards/partials/goal_add_form.html"

    def source(self, request: HttpRequest) -> tuple[str, Any, Metric]:
        params = request.POST if request.method == "POST" else request.GET
        if params.get("component"):
            card = visible_or_404(Component.objects.all(), request, key=params["component"])
            ct = get_component_type(card.type)
            if ct is None or not ct.single_value or not card.metric:
                raise Http404  # a card with a source of its own is saved as a metric first
            metric = get_object_or_404(Metric, key=card.metric)
            return "component", card, metric
        metric = visible_or_404(Metric.objects.all(), request, key=params.get("metric") or "")
        return "metric", metric, metric

    def render_form(
        self, request: HttpRequest, form: AddGoalForm, source: str, obj: Any, metric: Metric
    ) -> HttpResponse:
        template = self.partial_name if request.headers.get("HX-Request") else self.template_name
        return render(
            request,
            template,
            {
                "form": form,
                "source": source,
                "obj": obj,
                "metric": metric,
                "lists": form.lists,
                "current": evaluate(metric, request, period=None),
            },
        )

    def get(self, request: HttpRequest) -> HttpResponse:
        source, obj, metric = self.source(request)
        initial: dict[str, Any] = {"op": ">="}
        suggested = suggest_target(metric)
        for slot, prefix in (("target", ""), ("warn", "warn_")):
            rule = suggested.get(slot)
            if rule:
                initial[f"{prefix}op"] = rule["op"]
                value = rule["value"]
                initial[f"{prefix}value"], initial[f"{prefix}value2"] = (
                    (value[0], value[1]) if isinstance(value, list) else (value, None)
                )
        if request.GET.get("goal_list"):
            initial["goal_list"] = request.GET["goal_list"]
        form = AddGoalForm(initial=initial, user=request.user)
        return self.render_form(request, form, source, obj, metric)

    def post(self, request: HttpRequest) -> HttpResponse:
        source, obj, metric = self.source(request)
        form = AddGoalForm(request.POST, user=request.user)
        if form.is_valid():
            goal_list = form.chosen_list()
            try:
                add_goal(goal_list, form.goal(source, obj.key), form.cleaned_data.get("section") or "")
            except ValidationError as exc:
                for problem in exc.message_dict.get("sections", exc.messages):
                    form.add_error(None, problem)
            else:
                if request.headers.get("HX-Request"):
                    return render(request, "dashboards/partials/goal_added.html", {"goal_list": goal_list, "obj": obj})
                messages.success(request, f"Added “{obj.name}” to {goal_list.name}.")
                return redirect(goal_list.get_absolute_url())
        return self.render_form(request, form, source, obj, metric)


class ComponentPreviewView(LoginRequiredMixin, View):
    """One saved card, drawn exactly as a dashboard draws it — what the components
    page shows on hover and in its gallery. Access is the same as on a dashboard: a
    card over data you can't read says restricted."""

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        card = visible_or_404(Component.objects.all(), request, pk=pk)
        board = Dashboard(name="Preview", slug="preview", owner_id=card.owner_id)
        html = render_cell(board, {**card.as_cell(), "id": f"preview-{card.pk}", "name": card.name}, request, None)
        return render(request, "dashboards/partials/component_preview.html", {"card": card, "html": html})


class ComponentCreateMixin:
    """The component builder opened for a metric (``?metric=<key>``, from the
    metric's page or the "Save as metric" hand-off): the metric, the card
    type (``?type=``) and the group-by column (``?dimension=``, for the
    grouped types) arrive filled in, so the builder opens on the card the
    person asked for, not on an empty palette."""

    request: HttpRequest

    def get_initial(self) -> dict[str, Any]:
        initial: dict[str, Any] = super().get_initial()  # type: ignore[misc]
        g = self.request.GET
        # Duplicate: the builder opened with another card's settings, nothing
        # saved until Save — ``?from=<key>``, any card the person can see.
        original = Component.objects.filter(key=g.get("from", "").strip()).first()
        if original is not None and original.can_view(self.request.user):
            for field in ("description", "type", "metric", *SOURCE_KEYS, "options", "tags"):
                initial[field] = getattr(original, field)
            initial["name"] = f"{original.name} (copy)"[:120]
            initial["visibility"] = "personal"
            return initial
        key = g.get("metric", "").strip()
        metric = Metric.objects.filter(key=key).first() if key else None
        if metric is None or not metric.can_view(self.request.user):
            return initial
        ct = get_component_type(g.get("type", "").strip())
        if ct is not None:
            initial["type"] = ct.key
        if ct is not None and not ct.single_value and metric.source == SOURCE_DATASET:
            # A split or a chart filters a dataset of its own: it starts from the
            # metric's filter, format and rules, and goes its own way from there.
            initial.update({k: getattr(metric, k) for k in SOURCE_KEYS})
            style = {k: v for k, v in (("format", metric.format), ("unit", metric.unit)) if v and v != "number"}
            options: dict[str, Any] = {"style": style} if style else {}
            if metric.thresholds:
                options["thresholds"] = metric.thresholds
            initial["options"] = options
        else:
            initial["metric"] = metric.key
        # A group-by column only for a type that groups, and only a real column.
        dimension = g.get("dimension", "").strip()
        takes_dimension = ct is not None and any(o.get("name") == "dimension" for o in ct.options_schema)
        ds = get_dataset(metric.dataset) if dimension and takes_dimension and metric.dataset else None
        column = next((c for c in ds.schema()["columns"] if c["name"] == dimension), None) if ds is not None else None
        if column is None:
            initial["name"] = metric.name[:120]
            return initial
        initial["options"] = {**(initial.get("options") or {}), "dimension": dimension}
        initial["name"] = f"{metric.name} by {column['label']}"[:120]
        return initial


class ComponentListMixin:
    """The components list's own filter bar: the generic one offers a model
    column's raw values, but a card is found by *where its numbers come from*
    and *where it's shown* — the dataset (its own, or its metric's), the
    design, and the dashboard it's placed on (not a column at all: a dashboard
    names its cards in its layout). Each offers only what the person's cards
    use, labelled, so a library of hundreds narrows in a click or two."""

    request: HttpRequest
    crud_config: Any

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        if context.get("show_toolbar"):
            context["toolbar_filters"] = component_filters(self.request, self.crud_config)
            context["toolbar_has_active_filter"] = any(f["current_value"] for f in context["toolbar_filters"])
        return context


def component_filters(request: HttpRequest, cfg: Any) -> list[dict[str, Any]]:
    """The three dropdowns (``list_toolbar.html``'s choice shape), with the
    current ``?dashboard=``/``?dataset=``/``?type=`` selected."""
    from apps.datasets.registry import get_def

    cards = cfg.get_list_queryset(cfg._get_queryset(), request)
    user = getattr(request, "user", None)
    boards = Dashboard.objects.visible_to(user).active().order_by("name").values_list("slug", "name")
    via_metric = Metric.objects.filter(key__in=cards.exclude(metric="").values_list("metric", flat=True))
    datasets = set(cards.exclude(dataset="").values_list("dataset", flat=True)) | set(
        via_metric.exclude(dataset="").values_list("dataset", flat=True)
    )

    def label(key: str) -> str:
        dfn = get_def(key)
        return str(getattr(dfn, "label", "") or key) if dfn is not None else key

    present = set(cards.values_list("type", flat=True).distinct())
    designs = [(t.key, t.label) for t in component_types() if t.key in present]
    dataset_choices = sorted(((k, label(k)) for k in datasets), key=lambda p: p[1].lower())
    filters = [
        ("dashboard", "Dashboard", [("", "All")] + [(slug, name) for slug, name in boards]),
        ("dataset", "Dataset", [("", "All")] + dataset_choices),
        ("type", "Design", [("", "All")] + designs),
    ]
    return [
        {"name": name, "label": text, "type": "choice", "choices": choices, "current_value": request.GET.get(name, "")}
        for name, text, choices in filters
    ]


class ComponentCRUDView(_OwnedCRUD):
    """Saved cards — the component builder is this view's form page."""

    model = Component
    form_class = ComponentForm
    fields = ["name", "description", "type", "metric", *SOURCE_KEYS, "options", "tags"]
    list_fields = ["name", "type", "metric", "dataset", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/components"
    view_mixins = {
        Action.CREATE: [ComponentCreateMixin],
        Action.LIST: [ComponentListMixin],
        Action.DELETE: [ComponentDeleteMixin],
    }
    # ?dashboard=<slug> (the cards a dashboard shows), ?dataset=<key> (cards
    # over it, their own filter or their metric's), ?type=<design>. The first
    # two are served by apply_filter below, on the page and the REST list alike.
    filter_fields = ["dashboard", "dataset", "type"]
    displays = [ComponentLibraryDisplay, ComponentCardsDisplay]
    default_display = ComponentCardsDisplay  # the gallery first; the table is ?display=library
    search_fields = ["name", "key", "description", "metric", "dataset", "type", "tags"]
    ordering_fields = ["name", "type", "metric", "dataset", "updated_at"]
    api_extra_fields = ["key", "visibility", "owner", "created_by", "created_at", "updated_at", "provided_by"]
    mcp_singular = "component"
    mcp_plural = "components"
    mcp_lookup_field = "key"
    mcp_description = (
        "a saved dashboard card: type = a card type from list_dashboard_components (metric = single stat, "
        "metric_group = grouped stat with options.dimension, widget = info card, text = note, or an app's chart "
        "type), options = the type's options, and its source. A card that draws data filters a dataset of its own: "
        "dataset + filter_tree (metric_preview's shape) + agg/measure + period_field (the date column the period "
        "narrows and a chart buckets by), formatted by options.style {format, unit} and options.thresholds. The "
        "single-stat type may instead draw a saved metric (metric = its key), which is what makes it a goal. The "
        "key is made from the name. Place it on a dashboard with dashboard_add_card {component: key}; editing it "
        "updates every dashboard showing it. card_preview renders one unsaved"
    )

    @classmethod
    def apply_filter(cls, qs: Any, field_name: str, value: str, request: HttpRequest) -> Any:
        if field_name == "dashboard":
            # The cards the dashboard names in its layout; a dashboard the
            # person can't open narrows to nothing rather than to everything.
            board = Dashboard.objects.visible_to(getattr(request, "user", None)).filter(slug=value).first()
            if board is None:
                return qs.none()
            keys = {c.get("component") for c in board.layout or [] if isinstance(c, dict) and c.get("component")}
            return qs.filter(key__in=keys)
        if field_name == "dataset":
            over = Metric.objects.filter(dataset=value).values_list("key", flat=True)
            return qs.filter(Q(dataset=value) | Q(metric__in=over))
        return NotImplemented

    @classmethod
    def row_link_url(cls, obj: Any, request: HttpRequest) -> str:
        return str(obj.get_absolute_url())


__all__ = [
    "ComponentCRUDView",
    "DashboardCRUDView",
    "GoalListCRUDView",
    "MetricCRUDView",
    "PlaylistCRUDView",
    "ReportCRUDView",
]
