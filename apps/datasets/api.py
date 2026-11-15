"""REST surface for datasets under ``/smallstack/datasets/``.

Opt-in per dataset (``enable_api = True``) and gated by the site-wide
``SMALLSTACK_DATASETS_ENABLED`` master switch. Staff-only by default (secure
default for an admin-area data surface); a downstream project that wants a
broader-audience surface builds its own view over ``core.get_dataset``.

Routes:
    GET  /smallstack/datasets/                  → list (api-exposed datasets)
    GET  /smallstack/datasets/<key>/schema/     → typed columns + filters
    GET  /smallstack/datasets/<key>/series/     → grouped [{label, value}] (?sort=-value: a top N)
    GET  /smallstack/datasets/<key>/scalar/     → one aggregate {value}
    GET  /smallstack/datasets/<key>/cells/      → an x × y grid (?dimension=&dimension2=)
    GET  /smallstack/datasets/<key>/            → filtered rows

Every read route also takes ``?filter_tree=<json>`` — the nested AND/OR filter
(see filter_tree.py), AND-ed with the flat filter params. A malformed tree is a
400 naming each problem, never a silently wider result.
"""

from __future__ import annotations

from typing import Any, overload

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.smallstack.api import authenticate_api_request

from .core import Dataset, SafeCsvWriter, get_dataset, list_datasets
from .registry import get_def, user_may_view_model

_RESERVED = {
    "ordering",
    "limit",
    "offset",
    "format",
    "dimension",
    "dimension2",
    "sort",
    "measure",
    "agg",
    "expand",
    "buckets",
    "auto",
    "auto_limit",
    "label_field",
    "bucket",
    "filter_tree",
}


def _parse_filter_tree(request: HttpRequest) -> Any:
    """``?filter_tree=<json>`` → the tree (``None`` when absent). Raises
    ValueError on bad JSON (→ 400); the tree itself is validated by the
    dataset when it compiles."""
    import json

    raw = request.GET.get("filter_tree", "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"bad filter_tree JSON: {exc}") from exc


@overload
def _int_param(request: HttpRequest, name: str, default: int) -> int: ...
@overload
def _int_param(request: HttpRequest, name: str, default: None) -> int | None: ...
def _int_param(request: HttpRequest, name: str, default: int | None) -> int | None:
    """Parse an integer query param, falling back to ``default`` when absent or
    non-numeric. Query params arrive as strings; passing them straight to
    ``rows()``/``series()`` (which slice with them) would crash on ``?offset=5``."""
    raw = request.GET.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_sort(request: HttpRequest) -> dict | None:
    """``?sort=value`` / ``-value`` / ``category`` / ``-category`` → the
    ``series(sort=…)`` dict (a leading ``-`` is descending). None when absent;
    ValueError on anything else (→ 400)."""
    raw = request.GET.get("sort", "").strip()
    if not raw:
        return None
    by = raw.lstrip("-")
    if by not in ("category", "value"):
        raise ValueError(f"unknown sort {raw!r}; use category, -category, value or -value")
    return {"by": by, "dir": "desc" if raw.startswith("-") else "asc"}


def _parse_dimension(request: HttpRequest, field: str | None) -> dict | None:
    """Build a bucketed-dimension dict from query params, or None for raw mode.

    ``?buckets=<json-list>`` (hand-authored) and/or ``?auto=true&auto_limit=N&
    label_field=col`` turn a bare ``field`` into a bucketed dimension. Raises
    ValueError on malformed ``buckets`` JSON (→ 400).
    """
    import json

    raw_buckets = request.GET.get("buckets")
    auto = request.GET.get("auto", "").strip().lower() in ("true", "1", "yes")
    if not field or (not raw_buckets and not auto):
        return None
    dim: dict = {"field": field}
    if raw_buckets:
        try:
            parsed = json.loads(raw_buckets)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"bad buckets JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("buckets must be a JSON list of bucket objects")
        dim["buckets"] = parsed
    elif auto:
        opts: dict = {}
        if request.GET.get("auto_limit"):
            try:
                opts["limit"] = int(request.GET["auto_limit"])
            except (TypeError, ValueError):
                pass
        if request.GET.get("label_field"):
            opts["label_field"] = request.GET["label_field"]
        dim["auto"] = opts or True
    return dim


def _enabled() -> bool:
    return getattr(settings, "SMALLSTACK_DATASETS_ENABLED", True)


def _require_api_dataset(key: str, user: Any = None) -> Dataset:
    dfn = get_def(key)
    if dfn is None or not dfn.enable_api:
        raise Http404("dataset not found")
    # A dataset over a model the caller may not view answers as if absent.
    if user is not None and not user_may_view_model(dfn, user):
        raise Http404("dataset not found")
    ds = get_dataset(key)
    assert ds is not None  # guaranteed by the get_def check above
    return ds


def _parse_expand(request: HttpRequest) -> list[str]:
    raw = request.GET.get("expand", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _csv_cell(val: object) -> object:
    """Flatten a row value for a CSV cell (expanded FK dict → its name)."""
    if isinstance(val, dict) and "name" in val:
        return val["name"]
    if isinstance(val, bool):
        return str(val).lower()
    return "" if val is None else val


def _rows_csv_response(ds: Dataset, key: str, rows: list[dict]) -> HttpResponse:
    """Stream ``rows`` as CSV: schema columns first, then any extra keys."""
    header = list(ds.column_names())
    for row in rows:
        for k in row:
            if k not in header:
                header.append(k)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{key}.csv"'
    writer = SafeCsvWriter(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(row.get(col)) for col in header])
    return response


@method_decorator(csrf_exempt, name="dispatch")
class _DatasetApiView(View):
    """Base view: Bearer-or-session auth returning JSON 401/403 (never a 302).

    Uses the same ``authenticate_api_request`` path as ``/api/`` so a
    cross-origin SPA sending an ``Authorization: Bearer`` header can reach the
    datasets surface. Staff-only by default (secure default for an admin-area
    data surface), enforced as a JSON 403.
    """

    require_staff = True
    api_user: Any = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not _enabled():
            raise Http404
        user, err = authenticate_api_request(request)
        if err:
            return err
        if self.require_staff and not user.is_staff:
            return JsonResponse({"error": "Staff access required"}, status=403)
        self.api_user = user  # a bearer token's user isn't on request.user
        return super().dispatch(request, *args, **kwargs)


class DatasetListView(_DatasetApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        results = []
        for entry in list_datasets(api_only=True):
            dfn = get_def(entry["key"])
            if dfn is not None and user_may_view_model(dfn, self.api_user):
                results.append(entry)
        return JsonResponse({"results": results})


class DatasetSchemaView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key, self.api_user)
        return JsonResponse(ds.schema())


class DatasetRowsView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> HttpResponse:
        ds = _require_api_dataset(key, self.api_user)
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        is_csv = request.GET.get("format") == "csv"
        # CSV is the whole filtered set (an export), ignoring paging unless the
        # caller explicitly passes limit/offset; JSON pages (default limit 50).
        # Query params are strings — parse to int (rows() slices with them).
        # CSV is capped too (SMALLSTACK_DATASET_CSV_MAX_ROWS): it materializes
        # the whole set in memory. Over the cap is a loud 400, never a silently
        # truncated file.
        csv_cap = int(getattr(settings, "SMALLSTACK_DATASET_CSV_MAX_ROWS", 50_000))
        if is_csv:
            requested = _int_param(request, "limit", None)
            limit = csv_cap + 1 if requested is None or requested > csv_cap else requested
        else:
            limit = _int_param(request, "limit", 50)
        offset = _int_param(request, "offset", 0)
        # Bucket drilldown: ?dimension=…&(buckets|auto)…&bucket=<key> narrows the
        # rows to one bucket — the rows behind a clicked chart segment.
        bucket = request.GET.get("bucket") or None
        try:
            filter_tree = _parse_filter_tree(request)
            dimension = _parse_dimension(request, request.GET.get("dimension", "").strip() or None)
            rows = ds.rows(
                filters=filters,
                ordering=request.GET.get("ordering", ""),
                limit=limit,
                offset=offset,
                expand=_parse_expand(request),
                dimension=dimension,
                bucket=bucket,
                request=request,
                filter_tree=filter_tree,
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        if is_csv:
            if len(rows) > csv_cap:
                return JsonResponse(
                    {
                        "error": (
                            f"Export exceeds {csv_cap} rows (SMALLSTACK_DATASET_CSV_MAX_ROWS). "
                            "Narrow the filters, or page with limit/offset."
                        )
                    },
                    status=400,
                )
            return _rows_csv_response(ds, key, rows)
        offset_echo = max(0, offset)
        # ``total`` is the full matching count (of the bucket, if drilling down);
        # ``count`` stays the length of this page (unchanged for compatibility).
        return JsonResponse(
            {
                "key": key,
                "count": len(rows),
                "total": ds.count(
                    request=request, filters=filters, dimension=dimension, bucket=bucket, filter_tree=filter_tree
                ),
                "offset": offset_echo,
                "results": rows,
            }
        )


class DatasetSeriesView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key, self.api_user)
        # A blank/omitted dimension collapses to a single ungrouped aggregate
        # (the KPI/scalar path) instead of erroring.
        field = request.GET.get("dimension", "").strip() or None
        # Non-reserved query params are filters — same contract as the rows view,
        # so the chart reflects the builder's active filters.
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        try:
            # ?buckets=<json> / ?auto=true turn the field into a bucketed
            # dimension; otherwise it's raw-value grouping.
            bucketed = _parse_dimension(request, field)
            filter_tree = _parse_filter_tree(request)
            series = ds.series(
                bucketed if bucketed is not None else field,
                measure=(request.GET.get("measure") or None),
                agg=request.GET.get("agg", "count"),
                sort=_parse_sort(request),
                limit=_int_param(request, "limit", 50),
                filters=filters,
                request=request,
                filter_tree=filter_tree,
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"key": key, "dimension": field, "series": series})


class DatasetCellsView(_DatasetApiView):
    """Heatmap / punch card: ``?dimension=x&dimension2=y`` → a complete grid of
    ``[{x, x_label, y, y_label, value}]`` (see ``Dataset.cells``)."""

    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key, self.api_user)
        x = request.GET.get("dimension", "").strip()
        y = request.GET.get("dimension2", "").strip()
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        try:
            if not x or not y:
                raise ValueError("cells needs dimension and dimension2")
            cells = ds.cells(
                x,
                y,
                measure=(request.GET.get("measure") or None),
                agg=request.GET.get("agg", "count"),
                filters=filters,
                request=request,
                filter_tree=_parse_filter_tree(request),
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"key": key, "dimension": x, "dimension2": y, "cells": cells})


class DatasetScalarView(_DatasetApiView):
    """KPI tile: a single ungrouped aggregate → ``{value}`` (no GROUP BY)."""

    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key, self.api_user)
        agg = request.GET.get("agg", "count")
        measure = request.GET.get("measure") or None
        # Non-reserved query params are filters — same contract as the rows view,
        # so the KPI reflects the builder's active filters.
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        try:
            value = ds.scalar(
                measure=measure, agg=agg, filters=filters, request=request, filter_tree=_parse_filter_tree(request)
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"key": key, "agg": agg, "measure": measure, "value": value})
