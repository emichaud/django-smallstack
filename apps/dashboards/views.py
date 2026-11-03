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
from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, QuerySet
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
from apps.smallstack.pagination import PAGE_SIZE_CHOICES

from .boards import board_attention, board_cards, cell_value, render_cell, system_dashboard
from .comparison import compare_with_previous
from .components import available_widgets, describe_types, get_component_type
from .datasets import visible_entries
from .displays import (
    ComponentLibraryDisplay,
    DashboardLibraryDisplay,
    GoalListLibraryDisplay,
    MetricLibraryDisplay,
    PlaylistLibraryDisplay,
    ReportLibraryDisplay,
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
    threshold_legend,
    validate_drilldown,
)
from .models import (
    ADMIN_HOME_KEY,
    SNAPSHOT_CADENCES,
    Component,
    Dashboard,
    GoalList,
    Metric,
    OwnedModel,
    Playlist,
    Report,
    metric_usage,
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
        board_qs = Dashboard.objects.visible_to(user).select_related("owner")
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
        playlist_qs = Playlist.objects.visible_to(user)
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
        component_qs = Component.objects.visible_to(user)
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
                "metric_count": Metric.objects.visible_to(user).count(),
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
        goal_qs = GoalList.objects.visible_to(user)
        goal_count = goal_qs.count()
        if lists_order.lstrip("-") == "goals":
            lists = sorted(goal_qs, key=lambda g: (len(g.goals()), g.name.lower()), reverse=lists_order.startswith("-"))
        else:
            lists = list(apply_ordering(goal_qs, lists_order, {"name", "updated_at"})[: self.GOAL_LISTS])

        # -- metrics
        metrics_order, metrics_links = section_sort(
            request, "metrics", ("name", "source", "value"), "name", largest_first=("value",)
        )
        metric_qs = Metric.objects.visible_to(user).select_related("owner")
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
                }
            )
        if metrics_order.lstrip("-") == "value":
            numeric = [r for r in rows if r["result"].ok and is_number(r["result"].value)]
            rest = [r for r in rows if not (r["result"].ok and is_number(r["result"].value))]
            numeric.sort(key=lambda r: float(r["result"].value), reverse=metrics_order.startswith("-"))
            rows = numeric + rest

        # -- reports
        reports_order, reports_links = section_sort(
            request, "reports", ("name", "movement", "updated_at"), "-updated_at", largest_first=("updated_at",)
        )
        report_qs = Report.objects.visible_to(user).select_related("owner")
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
        qs: QuerySet = Dashboard.objects.mine(user).visible_to(user).order_by("-updated_at", "name")
        if field in ("name", "updated_at"):
            qs = apply_ordering(qs, ordering, {"name", "updated_at"})
        boards = list(qs)
        if field == "cards":
            boards.sort(key=lambda d: (len(d.layout), d.name.lower()), reverse=ordering.startswith("-"))
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
        return context

    def sort_links(self, request: HttpRequest, ordering: str) -> dict[str, dict[str, str]]:
        """Per sortable header: ``{url, aria_sort}`` — a click sorts ascending,
        a second click descending; other query params ride along."""
        out = {}
        for name in self.SORTS:
            params = request.GET.copy()
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
        cells = []
        for cell in dashboard.layout:
            ct = get_component_type(str(cell.get("type", "")))
            cells.append({**cell, "type_label": ct.label if ct else cell.get("type")})
        context.update(
            {
                "dashboard": dashboard,
                "cells": cells,
                "period": period or "all",
                "period_choices": period_choices(period),
                **period_nav(period),
                "can_edit": can_edit,
                "has_period_cells": any(c.get("metric") for c in dashboard.layout),
            }
        )
        if can_edit:
            context["editor"] = self.editor(dashboard, user)
        return context

    @staticmethod
    def editor(dashboard: Dashboard, user: Any) -> dict[str, Any]:
        """What edit mode offers: the layout, the card types, the metrics this
        dashboard may show (shared ones, plus its owner's), and staff widgets."""
        metrics = Metric.objects.visible_to(user)
        if dashboard.owner_id is None:
            metrics = metrics.filter(owner__isnull=True)
        else:
            metrics = metrics.filter(owner__isnull=True) | metrics.filter(owner_id=dashboard.owner_id)
        cards = Component.objects.visible_to(user).filter(owner__isnull=True)
        if dashboard.owner_id is not None:
            cards = cards | Component.objects.filter(owner_id=dashboard.owner_id)
        return {
            "layout": dashboard.layout,
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
        return HttpResponse(render_cell(dashboard, cell, request, period))


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
        dashboard.layout = layout
        try:
            dashboard.save()
        except ValidationError as exc:
            return JsonResponse({"errors": exc.message_dict.get("layout", exc.messages)}, status=400)
        return JsonResponse({"ok": True, "layout": dashboard.layout})


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
        context = drill_context(request, metric, drill, period, narrow)
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
            }
        )
        return render(request, "dashboards/partials/drill_rows.html", context)

    @staticmethod
    def drill_spec(request: HttpRequest, metric: Metric) -> tuple[Optional[dict[str, Any]], str]:
        """The card's drill-down design from ``?drill=<json>`` (what
        ``components.drill_params`` adds), validated against the metric's
        dataset — ``(spec or None, problem)``. It can only pick, label, format
        and sort columns of rows this viewer may already read."""
        raw = request.GET.get("drill")
        if not raw:
            return None, ""
        try:
            spec = json.loads(raw)
        except ValueError:
            return None, "Bad drill-down design."
        ds = get_dataset(metric.dataset)
        problems = validate_drilldown(spec, ds.column_names() if ds is not None else None)
        return (None, "; ".join(problems)) if problems else (spec, "")

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
        response["Content-Disposition"] = f'attachment; filename="{metric.key}-rows.csv"'
        writer = SafeCsvWriter(response)
        writer.writerow(headers)
        writer.writerows(rows)
        return response

    def period_links(self, request: HttpRequest, metric: Metric, period: Optional[str]) -> list[dict[str, Any]]:
        """Switch the modal's period in place, keeping any group narrowing.
        Empty for a metric without a period field — there's nothing to switch."""
        if not metric.period_field:
            return []
        base = reverse("dashboards_metric_rows", kwargs={"key": metric.key})
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
        metric, problems = unsaved_metric(request.user, payload)
        if metric is None or problems:
            return render(request, "dashboards/partials/drill_error.html", {"message": "; ".join(problems)}, status=400)
        period = str(payload.get("period") or "") or None
        try:
            order = MetricRowsView.valid_order(raw_order, metric)
            drill = drill_rows(metric, request, period=period, order=order)
            MetricRowsView.sort_links(request, drill)
        except (FilterTreeError, ValueError) as exc:
            return render(request, "dashboards/partials/drill_error.html", {"message": str(exc)}, status=400)
        context = {**drill_context(request, metric, drill, period), "unsaved": True}
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


class _OwnedCRUD(CRUDView):
    """Shared rules: list what you may view, edit what you may edit; forms
    stamp the owner (see forms.py)."""

    mixins = [LoginRequiredMixin]
    # "Rows per page" on every list here (15 by default), as on the datasets pages.
    page_sizes = PAGE_SIZE_CHOICES
    displays = [TableDisplay]
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
    api_extra_fields = ["visibility", "owner", "created_by", "created_at", "updated_at"]
    api_expand_fields = ["owner", "created_by"]

    @classmethod
    def get_list_queryset(cls, qs: Any, request: HttpRequest) -> Any:
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
    ]
    list_fields = ["name", "key", "source", "dataset", "agg", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/metrics"
    view_mixins = {Action.DELETE: [MetricDeleteMixin]}
    displays = [MetricLibraryDisplay, TableDisplay]
    search_fields = ["name", "key", "description", "dataset"]
    ordering_fields = ["name", "key", "dataset", "updated_at"]
    breadcrumb_parent = ("Goals", "goals_index")
    mcp_singular = "metric"
    mcp_plural = "metrics"
    mcp_lookup_field = "key"
    mcp_description = (
        "a metric: one named number (KPI). source says where it comes from: dataset (default: a stored filter "
        "over a dataset, rolled up), manual (values entered by hand with metric_record_value; agg is "
        "latest|sum|avg|min|max and dataset, measure, filter_tree and period_field are set for you) or rate "
        "(numerator and denominator are metric keys, divided over the same period; the percent format multiplies "
        "by 100). Fields: key (stable slug), name, source, numerator, denominator, dataset (a dataset key — see "
        "list_datasets / describe_dataset), filter_tree (nested "
        'AND/OR JSON: {"and": [{"field", "op", "value"}]}; ops: = != > >= < <= between in contains isnull '
        "period), agg (count|distinct|sum|avg|min|max), measure (column for non-count aggs), period_field "
        "(date column a dashboard period narrows), format (number|compact|decimal|percent|currency|duration), "
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
    ]
    list_fields = ["name", "slug", "default_period", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/boards"
    view_mixins = {Action.DELETE: [DashboardDeleteMixin]}
    displays = [DashboardLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description"]
    ordering_fields = ["name", "slug", "updated_at"]
    mcp_singular = "dashboard"
    mcp_plural = "dashboards"
    mcp_description = (
        "a dashboard: a grid of cards. layout is a list of cells on a 12-column grid — "
        '{"id", "type", "x", "y", "w", "h", "metric"?, "title"?, "options"?, "use_period"?}; types from '
        "list_dashboard_components (metric, metric_group with options.dimension, widget, text with "
        "options.markdown). default_period = a period key or blank; visibility = personal|shared. "
        "cover_image is the dashboard's picture: read-only here (its URL), uploaded as multipart over REST. "
        "dashboard_add_card appends one card without rewriting the layout"
    )


class ReportCRUDView(_OwnedCRUD):
    model = Report
    form_class = ReportForm
    fields = ["name", "slug", "description", "items", "periods"]
    list_fields = ["name", "slug", "periods", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/reports"
    view_mixins = {Action.DELETE: [ReportDeleteMixin]}
    displays = [ReportLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description"]
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
    fields = ["name", "slug", "description", "items", "seconds", "loop", "auto_start"]
    list_fields = ["name", "slug", "seconds", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/playlists"
    displays = [PlaylistLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description"]
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
    fields = ["name", "slug", "description", "default_period", "sections"]
    list_fields = ["name", "slug", "default_period", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/goals"
    view_mixins = {Action.CREATE: [_GoalListSavedMixin], Action.UPDATE: [_GoalListSavedMixin]}
    displays = [GoalListLibraryDisplay, TableDisplay]
    search_fields = ["name", "slug", "description"]
    ordering_fields = ["name", "slug", "default_period", "updated_at"]
    breadcrumb_parent = ("Goals", "goals_index")
    mcp_singular = "goal_list"
    mcp_plural = "goal_lists"
    mcp_description = (
        'a goal list: sections = [{"title": "Support", "goals": [goal, ...]}], each goal = {"metric": "<key>" '
        'or "component": "<single-stat card key>", "target": {"op": ">=", "value": 95}, "warn"?: {"op", '
        '"value"} (the at-risk line), "label"?, "period"?: "<key>"|"all", "note"?}; ops: > >= < <= = != '
        "between (value [low, high]). A goal is on target when its value meets target, at risk when it meets "
        "only warn, else missed. default_period = what goals without their own period are judged over (blank "
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
        from .snapshots import GRID_PERIODS, MAX_FILL, captures_of, history_grid, parse_period, tracked_cadences
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
        counts = {
            row["cadence"]: row["n"]
            for row in goal_list.snapshots.order_by().values("cadence").annotate(n=Count("pk"))
        }
        context.update(
            {
                "goal_list": goal_list,
                "cadence": cadence,
                "cadence_noun": SNAPSHOT_NOUNS[cadence],
                "tabs": [
                    {"key": k, "label": label, "tracked": k in tracked, "count": counts.get(k, 0)}
                    for k, label in SNAPSHOT_CADENCES
                ],
                "tracked": tracked,
                "grid": sort_grid(grid, order),
                "order": order,
                "sort_links": links,
                "grid_size": GRID_PERIODS[cadence],
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
            messages.success(request, f"Captured {done} past {SNAPSHOT_NOUNS[cadence]}{pluralize(done)}.")
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
            if ct is None or not ct.single_value:
                raise Http404
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


class ComponentCRUDView(_OwnedCRUD):
    """Saved cards — the component builder is this view's form page."""

    model = Component
    form_class = ComponentForm
    fields = ["name", "description", "type", "metric", "options"]
    list_fields = ["name", "type", "metric", "owner", "updated_at"]
    link_field = "name"
    field_transforms = {"owner": _owner_cell, "updated_at": "localtime"}
    url_base = "dashboards/components"
    displays = [ComponentLibraryDisplay, TableDisplay]
    search_fields = ["name", "key", "description", "metric", "type"]
    ordering_fields = ["name", "type", "metric", "updated_at"]
    api_extra_fields = ["key", "visibility", "owner", "created_by", "created_at", "updated_at"]
    mcp_singular = "component"
    mcp_plural = "components"
    mcp_lookup_field = "key"
    mcp_description = (
        "a saved dashboard card: type = a card type from list_dashboard_components (metric = single stat, "
        "metric_group = grouped stat with options.dimension, widget = info card, text = note, or an app's chart "
        "type), metric = a metric key for the types that draw one, options = the type's options. The key is made "
        "from the name. Place it on a dashboard with dashboard_add_card {component: key}; editing it updates "
        "every dashboard showing it. card_preview renders one unsaved"
    )

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
