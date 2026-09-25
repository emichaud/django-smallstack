"""REST surface for datasets under ``/smallstack/datasets/``.

Opt-in per dataset (``enable_api = True``) and gated by the site-wide
``SMALLSTACK_DATASETS_ENABLED`` master switch. Staff-only by default (secure
default for an admin-area data surface); a downstream project that wants a
broader-audience surface builds its own view over ``core.get_dataset``.

Routes:
    GET  /smallstack/datasets/                  → list (api-exposed datasets)
    GET  /smallstack/datasets/<key>/schema/     → typed columns + filters
    GET  /smallstack/datasets/<key>/series/     → grouped [{label, value}]
    GET  /smallstack/datasets/<key>/            → filtered rows
"""

from __future__ import annotations

import csv
from typing import overload

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.smallstack.api import _authenticate_api_request

from .core import Dataset, get_dataset, list_datasets
from .registry import get_def

_RESERVED = {
    "ordering", "limit", "offset", "format", "dimension", "measure", "agg", "expand",
    "buckets", "auto", "auto_limit", "label_field", "bucket",
}


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


def _require_api_dataset(key: str) -> Dataset:
    dfn = get_def(key)
    if dfn is None or not dfn.enable_api:
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
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_csv_cell(row.get(col)) for col in header])
    return response


@method_decorator(csrf_exempt, name="dispatch")
class _DatasetApiView(View):
    """Base view: Bearer-or-session auth returning JSON 401/403 (never a 302).

    Uses the same ``_authenticate_api_request`` path as ``/api/`` so a
    cross-origin SPA sending an ``Authorization: Bearer`` header can reach the
    datasets surface. Staff-only by default (secure default for an admin-area
    data surface), enforced as a JSON 403.
    """

    require_staff = True

    def dispatch(self, request, *args, **kwargs):
        if not _enabled():
            raise Http404
        user, err = _authenticate_api_request(request)
        if err:
            return err
        if self.require_staff and not user.is_staff:
            return JsonResponse({"error": "Staff access required"}, status=403)
        return super().dispatch(request, *args, **kwargs)


class DatasetListView(_DatasetApiView):
    def get(self, request: HttpRequest) -> JsonResponse:
        return JsonResponse({"results": list_datasets(api_only=True)})


class DatasetSchemaView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key)
        return JsonResponse(ds.schema())


class DatasetRowsView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> HttpResponse:
        ds = _require_api_dataset(key)
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        is_csv = request.GET.get("format") == "csv"
        # CSV is the whole filtered set (an export), ignoring paging unless the
        # caller explicitly passes limit/offset; JSON pages (default limit 50).
        # Query params are strings — parse to int (rows() slices with them).
        # CSV is capped too (SMALLSTACK_DATASET_CSV_MAX_ROWS): it materializes
        # the whole set in memory. Over the cap is a loud 400, never a silently
        # truncated file. (Audit 2026-09-13, C9c.)
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
                    request=request, filters=filters, dimension=dimension, bucket=bucket
                ),
                "offset": offset_echo,
                "results": rows,
            }
        )


class DatasetSeriesView(_DatasetApiView):
    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key)
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
            series = ds.series(
                bucketed if bucketed is not None else field,
                measure=(request.GET.get("measure") or None),
                agg=request.GET.get("agg", "count"),
                limit=_int_param(request, "limit", 50),
                filters=filters,
                request=request,
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"key": key, "dimension": field, "series": series})


class DatasetScalarView(_DatasetApiView):
    """KPI tile: a single ungrouped aggregate → ``{value}`` (no GROUP BY)."""

    def get(self, request: HttpRequest, key: str) -> JsonResponse:
        ds = _require_api_dataset(key)
        agg = request.GET.get("agg", "count")
        measure = request.GET.get("measure") or None
        # Non-reserved query params are filters — same contract as the rows view,
        # so the KPI reflects the builder's active filters.
        filters = {k: v for k, v in request.GET.items() if k not in _RESERVED}
        try:
            value = ds.scalar(
                measure=measure, agg=agg, filters=filters, request=request
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse(
            {"key": key, "agg": agg, "measure": measure, "value": value}
        )
