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
    GET  dashboards/api/boards/<slug>/values/       every card on a dashboard, evaluated
    POST dashboards/api/boards/<slug>/picture/      set the dashboard's picture (multipart: image, alt)
    DELETE dashboards/api/boards/<slug>/picture/    remove it
    GET  dashboards/api/reports/<slug>/values/      a report's matrix
    GET  dashboards/api/goals/<slug>/values/        a goal list judged: each goal's value, status, target (?period=)
    GET  dashboards/api/goals/<slug>/weeks/         the list week over week (?week=&weeks=), snapshots where saved
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

from apps.smallstack.api import authenticate_api_request

from .boards import board_values, clear_picture, set_picture
from .comparison import compare_with_previous
from .components import components_payload
from .forms import readable_datasets
from .goals import goal_values
from .metrics import evaluate
from .models import Dashboard, GoalList, Metric, Playlist, Report
from .periods import requested_period
from .playlists import playlist_payload
from .previews import preview_card, preview_metric, preview_report
from .reports import report_values
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
        return super().dispatch(request, *args, **kwargs)


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


class MetricValueApiView(_ApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        period = requested_period(request)
        result = evaluate(metric, request, period=period)
        comparison = compare_with_previous(metric, request, period, result)
        return JsonResponse({"key": metric.key, "name": metric.name, **result.as_dict(), "comparison": comparison})


class MetricTrendApiView(_ApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        metric = _visible(Metric, request.user, key=key)
        trend = metric_trend(metric, request, requested_period(request), request.GET.get("grain") or None)
        return JsonResponse({"key": metric.key, "name": metric.name, **trend})


class BoardValuesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        dashboard = _visible(Dashboard, request.user, slug=slug)
        period = requested_period(request, dashboard.default_period)
        return JsonResponse(
            {
                "slug": dashboard.slug,
                "name": dashboard.name,
                "period": period,
                "url": dashboard.get_absolute_url(),
                "cells": board_values(dashboard, request, period),
            }
        )


def _no_response(request: HttpRequest) -> HttpResponse:
    return HttpResponse()  # never called: only the check (process_view) runs


class BoardPictureApiView(_ApiView):
    """The one write on these routes, because the generic CRUD endpoint takes
    JSON and a picture is a file. ``POST`` multipart (``image``, optional
    ``alt``) sets it; ``DELETE`` removes it.

    ``_ApiView`` is CSRF-exempt for its token callers, and a cross-site form
    *can* post multipart, so a session caller gets Django's CSRF check here
    (send ``X-CSRFToken``, as the page's own fetches do). A read-only token is
    refused like on the CRUD routes."""

    def _write_allowed(self, request: HttpRequest) -> JsonResponse | None:
        token = getattr(request, "_api_token", None)
        if token is not None:
            if getattr(token, "access_level", "") == "readonly":
                return JsonResponse({"error": "Token is read-only"}, status=403)
            return None
        if CsrfViewMiddleware(_no_response).process_view(request, _no_response, (), {}) is not None:
            return JsonResponse({"error": "CSRF check failed — send the X-CSRFToken header"}, status=403)
        return None

    def _editable(self, request: HttpRequest, slug: str) -> Dashboard | JsonResponse:
        refused = self._write_allowed(request)
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
        # No ?period= → the list's own; ?period=all → all time ("").
        period = (requested_period(request) or "") if "period" in request.GET else None
        return JsonResponse(goal_values(goal_list, request, period=period))


class GoalWeeksApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        from .weeks import GRID_WEEKS, parse_week, this_week, week_grid, weeks_payload

        goal_list = _visible(GoalList, request.user, slug=slug)
        last = min(parse_week(request.GET.get("week")) or this_week(), this_week())
        try:
            count = max(1, min(int(request.GET.get("weeks") or GRID_WEEKS), 26))
        except ValueError:
            count = GRID_WEEKS
        return JsonResponse(weeks_payload(goal_list, week_grid(goal_list, request, last, count)))


class ReportValuesApiView(_ApiView):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        report = _visible(Report, request.user, slug=slug)
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
