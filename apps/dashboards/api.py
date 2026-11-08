"""JSON routes for builders and agents — Bearer token or session.

The CRUD (create/update/list a metric, dashboard or report) comes from the
CRUDViews at ``/smallstack/api/…``; these are the *evaluation* routes a CRUD
row can't express:

    GET  dashboards/api/components/                 the card types + periods (+ widgets for staff)
    GET  dashboards/api/datasets/                   datasets you may build on
    GET  dashboards/api/datasets/<key>/schema/      a dataset's columns, filter ops, periods
    POST dashboards/api/preview/                    evaluate an UNSAVED metric (dry run)
    GET  dashboards/api/metrics/<key>/value/        evaluate a saved metric (?period=)
    GET  dashboards/api/metrics/<key>/trend/        the metric per bucket (?period=&grain=) — for charts
    GET  dashboards/api/metrics/<key>/rows/         the rows behind the number (?period=&order=&limit=&drill=)
    GET  dashboards/api/boards/<slug>/values/       every card on a dashboard, evaluated
    POST dashboards/api/boards/<slug>/picture/      set the dashboard's picture (multipart: image, alt)
    DELETE dashboards/api/boards/<slug>/picture/    remove it
    GET  dashboards/api/reports/<slug>/values/      a report's matrix
    GET  dashboards/api/goals/<slug>/values/        a goal list judged: each goal's value, status, target (?period=)
    GET  dashboards/api/goals/<slug>/weeks/         the list week over week (?week=&weeks=), snapshots where saved
    POST dashboards/api/goals/<slug>/weeks/<week>/save/  save that week's values and targets
    GET  dashboards/api/playlists/<slug>/slides/    a playlist as the caller sees it: slides, dwell, periods
    POST dashboards/api/report-preview/             evaluate an UNSAVED report
    POST dashboards/api/card-preview/               render an UNSAVED card (the component builder's preview)

Each route parses the request and returns what a service function computes
(``previews``, ``boards``, ``reports``, ``comparison``, ``components``) — the
same functions the MCP tools and the pages call, so the surfaces can't drift.

An agent's loop: datasets → schema → preview (iterate until ``problems`` is
empty and the value looks right) → create the metric → create/patch a
dashboard → read ``boards/<slug>/values/`` to check its work.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.datasets.core import GRAINS
from apps.smallstack.api import authenticate_api_request

from .boards import board_values, clear_picture, set_picture
from .comparison import compare_with_previous
from .components import components_payload, link_warnings
from .datasets import visible_entries
from .entries import parse_entry, record_entry
from .forms import readable_datasets
from .goals import goal_values
from .metrics import drill_rows, evaluate, may_read, requested_drilldown
from .models import Dashboard, GoalList, Metric, Playlist, Report
from .periods import NO_PERIOD_FIELD_NOTE, period_problem, requested_period
from .playlists import playlist_payload
from .previews import preview_card, preview_metric, preview_report
from .reports import report_matrix, report_values, write_report_csv
from .trends import metric_trend


def _enabled() -> bool:
    return getattr(settings, "SMALLSTACK_DASHBOARDS_ENABLED", True)


@method_decorator(csrf_exempt, name="dispatch")
class _ApiView(View):
    """Bearer-or-session auth with JSON 401s (never a login redirect).

    CSRF-exempt like the framework's own ``@api_view`` and generated REST
    routes. Safe here because the POSTs are dry runs (a preview evaluates, it
    never saves), and a cross-site page can't read the response. A route that
    saves belongs on the CRUDView — the one exception, the picture upload
    (a file the JSON CRUD can't carry), runs the CSRF check itself."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not _enabled():
            raise Http404
        user, err = authenticate_api_request(request)
        if err:
            return err
        request.user = user
        try:
            return super().dispatch(request, *args, **kwargs)
        except Http404:
            # JSON like every other answer here, not the site's HTML page. Says
            # the same for "isn't there" and "isn't yours" (see _visible).
            return JsonResponse({"error": "not found"}, status=404)


class ComponentsApiView(_ApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        return JsonResponse(components_payload(request.user))


class DatasetsApiView(_ApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        from apps.datasets.registry import get_def

        out = []
        for key, label in readable_datasets(request.user):
            dfn = get_def(key)
            out.append({"key": key, "label": label, "description": dfn.description if dfn else ""})
        return JsonResponse({"results": out})


class DatasetSchemaApiView(_ApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        return _schema_response(request.user, key)


def _schema_response(user: Any, key: str) -> JsonResponse:
    from apps.datasets.core import get_dataset
    from apps.datasets.registry import get_def, user_may_read

    dfn = get_def(key)
    ds = get_dataset(key) if dfn is not None and user_may_read(dfn, user) else None
    if ds is None:
        return JsonResponse({"error": f"unknown dataset {key!r}"}, status=404)
    return JsonResponse(ds.schema())


class PreviewApiView(_ApiView):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"ok": False, "problems": ["body must be JSON"]}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"ok": False, "problems": ["body must be a JSON object"]}, status=400)
        out = preview_metric(request.user, payload, request=request)
        return JsonResponse(out, status=200 if out.get("ok") or out.get("result") else 400)


def _visible(model: Any, user: Any, **lookup: Any) -> Any:
    obj = model.objects.filter(**lookup).first()
    if obj is None or not obj.can_view(user):
        raise Http404
    return obj


def _period_refused(request: HttpRequest) -> JsonResponse | None:
    """A 400 for a ``?period=`` that isn't one. ``requested_period`` falls back
    quietly, which suits a page; a client reading a number can't tell it got all
    time instead of the week it asked for."""
    problem = period_problem(request.GET.get("period"))
    return JsonResponse({"error": problem}, status=400) if problem else None


class MetricValueApiView(_ApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        refused = _period_refused(request)
        if refused:
            return refused
        period = requested_period(request)
        result = evaluate(metric, request, period=period)
        comparison = compare_with_previous(metric, request, period, result)
        out = {"key": metric.key, "name": metric.name, **result.as_dict(), "comparison": comparison}
        if period and not metric.period_field:
            out["note"] = NO_PERIOD_FIELD_NOTE
        return JsonResponse(out)


class MetricEntriesApiView(_ApiView):
    """A hand-entered metric's values: GET lists them, newest first; POST
    ``{date, value, note?}`` sets one, replacing any earlier value for that date."""

    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        entries = visible_entries(request.user).filter(metric=metric)[:500]
        return JsonResponse(
            {
                "key": metric.key,
                "entries": [{"date": e.date.isoformat(), "value": float(e.value), "note": e.note} for e in entries],
            }
        )

    def post(self, request: HttpRequest, key: str) -> JsonResponse:
        refused = _write_refused(request)
        if refused:
            return refused
        metric = _visible(Metric, request.user, key=key)
        if not metric.can_edit(request.user):
            return JsonResponse({"error": "You can't edit this metric."}, status=403)
        if not metric.is_manual:
            return JsonResponse({"error": "This metric isn't entered by hand."}, status=400)
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "The body must be JSON."}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "The body must be a JSON object."}, status=400)
        day, value, errors = parse_entry(payload.get("date"), payload.get("value"))
        if errors or day is None or value is None:
            return JsonResponse({"errors": errors}, status=400)
        entry = record_entry(metric, day, value, str(payload.get("note") or ""), by=request.user)
        return JsonResponse({"key": metric.key, "date": entry.date.isoformat(), "value": float(entry.value)})


class MetricTrendApiView(_ApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        refused = _period_refused(request)
        if refused:
            return refused
        grain = request.GET.get("grain") or None
        if grain and grain not in GRAINS:
            return JsonResponse({"error": f"unknown grain {grain!r} — use one of {', '.join(GRAINS)}"}, status=400)
        trend = metric_trend(metric, request, requested_period(request), grain)
        return JsonResponse({"key": metric.key, "name": metric.name, **trend})


class MetricRowsApiView(_ApiView):
    """The rows behind the number, as JSON (``m/<key>/rows/`` is the modal's
    HTML). ``?drill=<json>`` is a card's drill-down design — its columns,
    headings, formats and sort (and its own row limit, when it sets one) —
    which is how the component builder shows the rows a design opens."""

    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        if not may_read(metric, request.user):
            return JsonResponse({"error": "you don't have access to this metric's data"}, status=403)
        refused = _period_refused(request)
        if refused:
            return refused
        try:
            limit = max(1, min(int(request.GET.get("limit") or 25), 200))
        except ValueError:
            return JsonResponse({"error": "limit must be a whole number"}, status=400)
        spec, problem = requested_drilldown(request.GET.get("drill"), metric)
        if problem:
            return JsonResponse({"error": problem}, status=400)
        try:
            rows = drill_rows(
                metric,
                request,
                period=requested_period(request),
                limit=limit,
                spec=spec,
                order=request.GET.get("order") or "",
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(json.loads(json.dumps(rows, default=str)))


class PreviewRowsApiView(_ApiView):
    """The same rows for an UNSAVED source (``POST dashboards/api/preview-rows/``):
    a card's own definition (``dataset``, ``filter_tree``, ``agg``, ``measure``,
    ``period_field``) plus ``period``, ``limit``, ``drill`` and ``order`` in the
    body. The component builder's drill-down designer reads a card that filters
    a dataset itself through this."""

    def post(self, request: HttpRequest) -> JsonResponse:
        from .previews import unsaved_metric

        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            return JsonResponse({"error": "body must be a JSON object"}, status=400)
        metric, problems = unsaved_metric(request.user, payload)
        if metric is None or problems:
            return JsonResponse({"error": "; ".join(problems)}, status=400)
        period = str(payload.get("period") or "") or None
        problem = period_problem(period)
        if problem:
            return JsonResponse({"error": problem}, status=400)
        try:
            limit = max(1, min(int(payload.get("limit") or 25), 200))
        except (TypeError, ValueError):
            return JsonResponse({"error": "limit must be a whole number"}, status=400)
        raw_drill = payload.get("drill")
        spec, problem = requested_drilldown(
            raw_drill if isinstance(raw_drill, str) or raw_drill is None else json.dumps(raw_drill), metric
        )
        if problem:
            return JsonResponse({"error": problem}, status=400)
        try:
            rows = drill_rows(
                metric, request, period=period, limit=limit, spec=spec, order=str(payload.get("order") or "")
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(json.loads(json.dumps(rows, default=str)))


class BoardValuesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        dashboard = _visible(Dashboard, request.user, slug=slug)
        refused = _period_refused(request)
        if refused:
            return refused
        period = requested_period(request, dashboard.default_period)
        return JsonResponse(
            {
                "slug": dashboard.slug,
                "name": dashboard.name,
                "period": period,
                "url": dashboard.get_absolute_url(),
                "cells": board_values(dashboard, request, period),
                **({"warnings": warnings} if (warnings := link_warnings(dashboard.layout)) else {}),
            }
        )


def _no_response(request: HttpRequest) -> HttpResponse:
    return HttpResponse()  # never called: only the check (process_view) runs


def _write_refused(request: HttpRequest) -> JsonResponse | None:
    token = getattr(request, "_api_token", None)
    if token is not None:
        if getattr(token, "access_level", "") == "readonly":
            return JsonResponse({"error": "Token is read-only"}, status=403)
        return None
    if CsrfViewMiddleware(_no_response).process_view(request, _no_response, (), {}) is not None:
        return JsonResponse({"error": "CSRF check failed — send the X-CSRFToken header"}, status=403)
    return None


class BoardPictureApiView(_ApiView):
    """The one write on these routes, because the generic CRUD endpoint takes
    JSON and a picture is a file. ``POST`` multipart (``image``, optional
    ``alt``) sets it; ``DELETE`` removes it.

    ``_ApiView`` is CSRF-exempt for its token callers, and a cross-site form
    *can* post multipart, so a session caller gets Django's CSRF check here
    (send ``X-CSRFToken``, as the page's own fetches do). A read-only token is
    refused like on the CRUD routes."""

    def _editable(self, request: HttpRequest, slug: str) -> Dashboard | JsonResponse:
        refused = _write_refused(request)
        if refused:
            return refused
        dashboard = _visible(Dashboard, request.user, slug=slug)
        if not dashboard.can_edit(request.user):
            return JsonResponse({"error": "you may not edit this dashboard"}, status=403)
        return dashboard

    def post(self, request: HttpRequest, slug: str) -> JsonResponse:
        dashboard = self._editable(request, slug)
        if isinstance(dashboard, JsonResponse):
            return dashboard
        image = request.FILES.get("image")
        if image is None:
            return JsonResponse({"error": "send the picture as a multipart file field named image"}, status=400)
        out = set_picture(dashboard, image, str(request.POST.get("alt") or ""))
        return JsonResponse(out, status=400 if "error" in out else 200)

    def delete(self, request: HttpRequest, slug: str) -> JsonResponse:
        dashboard = self._editable(request, slug)
        if isinstance(dashboard, JsonResponse):
            return dashboard
        return JsonResponse(clear_picture(dashboard))


class PlaylistSlidesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        return JsonResponse(playlist_payload(_visible(Playlist, request.user, slug=slug), request.user))


class GoalValuesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        goal_list = _visible(GoalList, request.user, slug=slug)
        refused = _period_refused(request)
        if refused:
            return refused
        # No ?period= → the list's own; ?period=all → all time ("").
        period = (requested_period(request) or "") if "period" in request.GET else None
        return JsonResponse(goal_values(goal_list, request, period=period))


class GoalWeeksApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .weeks import GRID_WEEKS, parse_week, this_week, week_grid, weeks_payload

        goal_list = _visible(GoalList, request.user, slug=slug)
        if request.GET.get("week") and parse_week(request.GET["week"]) is None:
            return JsonResponse(
                {"error": f"unknown week {request.GET['week']!r} — use a date (2026-11-02) or an ISO week (2026-W45)"},
                status=400,
            )
        last = min(parse_week(request.GET.get("week")) or this_week(), this_week())
        try:
            count = max(1, min(int(request.GET.get("weeks") or GRID_WEEKS), 26))
        except ValueError:
            return JsonResponse({"error": "weeks must be a whole number"}, status=400)
        return JsonResponse(weeks_payload(goal_list, week_grid(goal_list, request, last, count)))


class GoalWeekSaveApiView(_ApiView):
    """Save a week (``g/<slug>/weeks/<week>/snapshot/`` is the page's form). A
    token write like the picture's: read-only tokens are refused, and a session
    caller needs the CSRF header."""

    def post(self, request: HttpRequest, slug: str, week: str) -> JsonResponse:
        from .weeks import parse_week, take_snapshot

        refused = _write_refused(request)
        if refused:
            return refused
        goal_list = _visible(GoalList, request.user, slug=slug)
        if not goal_list.can_edit(request.user):
            return JsonResponse({"error": "you may not edit this goal list"}, status=403)
        start = parse_week(week)
        if start is None:
            return JsonResponse({"error": f"unknown week {week!r} — use a date or an ISO week (2026-W45)"}, status=400)
        try:
            snapshot = take_snapshot(goal_list, start, by=request.user)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"ok": True, "week": snapshot.week_start.isoformat(), "summary": snapshot.summary})


class GoalSnapshotsApiView(_ApiView):
    """GET ``?cadence=``: the list's captures, goals down and periods across. POST
    ``{cadence, fill?}``: capture the current period, or fill in the past *fill*."""

    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .snapshots import history_grid, history_payload, tracked_cadences

        goal_list = _visible(GoalList, request.user, slug=slug)
        tracked = tracked_cadences(goal_list)
        cadence = request.GET.get("cadence") or (tracked[0] if tracked else "weekly")
        try:
            grid = history_grid(goal_list, request, cadence)
        except (KeyError, ValueError):
            return JsonResponse({"error": f"unknown cadence {cadence!r}"}, status=400)
        return JsonResponse(history_payload(goal_list, grid))

    def post(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .snapshots import capture, current_period, fill

        refused = _write_refused(request)
        if refused:
            return refused
        goal_list = _visible(GoalList, request.user, slug=slug)
        if not goal_list.can_edit(request.user):
            return JsonResponse({"error": "you may not edit this goal list"}, status=403)
        try:
            payload = json.loads(request.body or b"{}")
            cadence = str(payload.get("cadence") or "")
            if payload.get("fill") is not None:
                if int(payload["fill"]) < 1:
                    return JsonResponse({"error": "fill is how many past periods to capture: 1 or more."}, status=400)
                done = fill(goal_list, cadence, int(payload["fill"]), by=request.user)
                return JsonResponse({"ok": True, "captured": done})
            snapshot = capture(goal_list, current_period(cadence), by=request.user)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return JsonResponse({"error": f"send a cadence: {exc}"}, status=400)
        return JsonResponse({"ok": True, "period": snapshot.period_start.isoformat(), "summary": snapshot.summary})


class GoalTrackingApiView(_ApiView):
    """GET: the cadences this list tracks. POST ``{cadences: [...]}``: track exactly those."""

    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .snapshots import tracked_cadences

        return JsonResponse({"tracked": tracked_cadences(_visible(GoalList, request.user, slug=slug))})

    def post(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .snapshots import set_tracking

        refused = _write_refused(request)
        if refused:
            return refused
        goal_list = _visible(GoalList, request.user, slug=slug)
        if not goal_list.can_edit(request.user):
            return JsonResponse({"error": "you may not edit this goal list"}, status=403)
        try:
            cadences = json.loads(request.body or b"{}")["cadences"]
            if not isinstance(cadences, list):
                raise ValueError("cadences must be a list")
            return JsonResponse({"tracked": set_tracking(goal_list, cadences, by=request.user)})
        except (ValueError, KeyError, TypeError) as exc:
            return JsonResponse({"error": f"send {{\"cadences\": [...]}}: {exc}"}, status=400)


class ReportValuesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        report = _visible(Report, request.user, slug=slug)
        if request.GET.get("format") == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="{report.slug}.csv"'
            write_report_csv(report_matrix(report, request), response)
            return response
        return JsonResponse(report_values(report, request))


class CardPreviewApiView(_ApiView):
    """Dry run: renders the card, saves nothing."""

    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "body must be JSON"}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "body must be a JSON object"}, status=400)
        return JsonResponse(preview_card(request.user, payload, request))


class ReportPreviewApiView(_ApiView):
    def post(self, request: HttpRequest) -> JsonResponse:
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"error": "body must be JSON"}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "body must be a JSON object"}, status=400)
        return JsonResponse(json.loads(json.dumps(preview_report(request.user, payload, request=request), default=str)))


_openapi_registered = False


def register_openapi_paths() -> None:
    """Put these routes in ``/api/schema/openapi.json`` beside the generated CRUD."""
    global _openapi_registered
    if _openapi_registered:
        return
    _openapi_registered = True

    from apps.smallstack.api import register_api_path

    def path_param(name: str) -> dict[str, Any]:
        return {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}

    def query(name: str, description: str) -> dict[str, Any]:
        schema = {"type": "string"}
        return {"name": name, "in": "query", "required": False, "schema": schema, "description": description}

    period = query("period", "A period key (mtd, pwtd, last_30…) or 'all'. An unknown one is a 400.")
    key, slug = path_param("key"), path_param("slug")
    body = {"required": True, "content": {"application/json": {"schema": {"type": "object"}}}}
    routes: list[tuple[str, str, str, list[dict[str, Any]]]] = [
        ("GET", "components/", "Card types, periods and style vocabulary", []),
        ("GET", "datasets/", "Datasets you may build on", []),
        ("GET", "datasets/{key}/schema/", "A dataset's columns, filter ops and periods", [key]),
        ("POST", "preview/", "Evaluate an unsaved metric (dry run)", []),
        (
            "GET",
            "goals/{slug}/snapshots/",
            "A goal list's captures for one cadence",
            [slug, query("cadence", "hourly, daily, weekly, monthly or quarterly.")],
        ),
        ("POST", "goals/{slug}/snapshots/", "Capture the current period, or fill in past ones", [slug]),
        ("GET", "goals/{slug}/tracking/", "The cadences a goal list tracks", [slug]),
        ("POST", "goals/{slug}/tracking/", "Set the cadences a goal list tracks", [slug]),
        ("GET", "metrics/{key}/entries/", "A hand-entered metric's values", [key]),
        ("POST", "metrics/{key}/entries/", "Set a hand-entered metric's value for a date", [key]),
        ("POST", "report-preview/", "Evaluate an unsaved report (dry run)", []),
        ("POST", "card-preview/", "Render an unsaved card (dry run)", []),
        ("GET", "metrics/{key}/value/", "A saved metric's value", [key, period]),
        (
            "GET",
            "metrics/{key}/trend/",
            "A saved metric per bucket",
            [key, period, query("grain", "day, week, month, quarter or year")],
        ),
        (
            "GET",
            "metrics/{key}/rows/",
            "The rows behind a metric's number",
            [key, period, query("order", "A column, - for descending"), query("limit", "1-200, default 25")],
        ),
        ("GET", "boards/{slug}/values/", "Every card on a dashboard, evaluated", [slug, period]),
        ("GET", "reports/{slug}/values/", "A report's matrix", [slug, query("format", "csv for the CSV download")]),
        ("GET", "goals/{slug}/values/", "A goal list judged", [slug, period]),
        (
            "GET",
            "goals/{slug}/weeks/",
            "A goal list week over week",
            [slug, query("week", "The last week: a date or 2026-W45"), query("weeks", "How many, 1-26")],
        ),
        ("POST", "goals/{slug}/weeks/{week}/save/", "Save a week's values and targets", [slug, path_param("week")]),
        ("GET", "playlists/{slug}/slides/", "A playlist as the caller sees it", [slug]),
    ]
    for method, subpath, summary, parameters in routes:
        register_api_path(
            "dashboards_index",
            subpath=f"api/{subpath}",
            methods=[method],
            summary=summary,
            tags=["Dashboards"],
            parameters=parameters,
            request_body=body if subpath.endswith("preview/") else None,
        )
