"""The staff dataset browser — ``/smallstack/datasets/browse/``.

A thin, generic UI over the ``@dataset`` contract: the index lists every
registered dataset; the browse page builds its filter bar from
``schema()["filters"]``, its table from ``schema()["columns"]``, pages through
``queryset()`` and offers a one-dimension roll-up via ``series()``. It never
hard-codes a model or a column — the same page serves the bundled
``smallstack_*`` datasets and whatever a downstream project declares.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from django.core.paginator import Page
from django.db.models import QuerySet
from django.http import Http404, HttpRequest
from django.urls import reverse
from django.views.generic import TemplateView

from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.pagination import paginate_queryset
from apps.smallstack.sorting import build_sort_headers

from .core import Dataset, get_dataset, list_datasets
from .framework import is_framework_dataset
from .registry import get_def

PAGE_SIZE = 50
SERIES_LIMIT = 50
AGG_CHOICES = (("count", "Count"), ("sum", "Sum"), ("avg", "Average"), ("min", "Min"), ("max", "Max"))

#: Query params the browse page owns; everything else is a dataset filter.
_PAGE_PARAMS = {"ordering", "page", "group_by", "measure", "agg"}


class DatasetIndexView(StaffRequiredMixin, TemplateView):
    template_name = "datasets/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        framework: list[dict[str, Any]] = []
        project: list[dict[str, Any]] = []
        for entry in list_datasets():
            ds = get_dataset(entry["key"])
            dfn = get_def(entry["key"])
            if ds is None or dfn is None:
                continue
            try:
                cols = ds.columns()  # DB-free
            except Exception:  # noqa: BLE001 — a broken dataset must not hide the rest
                cols = []
            measures = sum(1 for _, typ in cols if typ in ("integer", "float", "decimal"))
            measures += len(ds.declared_measures())
            row = {
                **entry,
                "columns": len(cols),
                "measures": measures,
                "enable_api": dfn.enable_api,
                "enable_mcp": dfn.enable_mcp,
                "url": reverse("datasets:browse", kwargs={"key": entry["key"]}),
            }
            (framework if is_framework_dataset(entry["key"]) else project).append(row)
        framework.sort(key=lambda r: r["label"].lower())
        project.sort(key=lambda r: r["label"].lower())
        context.update(
            {
                "framework_datasets": framework,
                "project_datasets": project,
                "total": len(framework) + len(project),
            }
        )
        return context


class DatasetBrowseView(StaffRequiredMixin, TemplateView):
    template_name = "datasets/browse.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        key: str = kwargs["key"]
        ds = get_dataset(key)
        dfn = get_def(key)
        if ds is None or dfn is None:
            raise Http404(f"No dataset {key!r}")
        request = self.request
        schema = ds.schema()
        columns: list[dict[str, Any]] = [c for c in schema["columns"] if not c.get("computed")]
        declared = [c for c in schema["columns"] if c.get("computed")]

        filters = self._active_filters(request, ds, schema)
        ordering = request.GET.get("ordering", "").strip()
        page_obj = self._page(request, ds, filters, ordering)

        rows = [{"url": ds.link_for(obj), "cells": self._cells(obj, columns)} for obj in page_obj.object_list]
        headers = build_sort_headers([(c["name"], c["label"]) for c in columns], ordering)
        for header, col in zip(headers, columns):
            header["type"] = col["type"]

        context.update(
            {
                "dataset": ds,
                "dfn": dfn,
                "schema": schema,
                "columns": columns,
                "headers": headers,
                "widgets": self._widgets(schema, request),
                "filters": filters,
                "has_filters": bool(filters),
                "page_obj": page_obj,
                "rows": rows,
                "has_links": ds.has_links(),
                "csv_url": self._csv_url(key, dfn.enable_api, filters),
                "is_framework": is_framework_dataset(key),
                **self._rollup(request, ds, schema, declared, filters),
            }
        )
        return context

    # -- filters -------------------------------------------------------------

    @staticmethod
    def _active_filters(request: HttpRequest, ds: Dataset, schema: dict[str, Any]) -> dict[str, str]:
        """The non-empty query params that are real dataset filters (or a
        ``<datecol>__gte``/``__lt`` bound on one)."""
        allowed = set(ds.filter_field_names())
        out: dict[str, str] = {}
        for name, raw in request.GET.items():
            value = str(raw).strip()
            if not value or name in _PAGE_PARAMS:
                continue
            base, sep, lookup = name.partition("__")
            if name in allowed or (sep and lookup in ("gte", "lt") and base in allowed):
                out[name] = value
        return out

    @staticmethod
    def _widgets(schema: dict[str, Any], request: HttpRequest) -> list[dict[str, Any]]:
        """Filter controls straight from ``schema()["filters"]`` with the
        current values filled in — the UI never infers a widget from a type."""
        widgets: list[dict[str, Any]] = []
        for meta in schema["filters"]:
            name = meta["name"]
            widget = dict(meta)
            widget["value"] = request.GET.get(name, "")
            if meta.get("range"):
                widget["gte"] = request.GET.get(f"{name}__gte", "")
                widget["lt"] = request.GET.get(f"{name}__lt", "")
            widgets.append(widget)
        return widgets

    # -- rows ----------------------------------------------------------------

    @staticmethod
    def _page(request: HttpRequest, ds: Dataset, filters: dict[str, str], ordering: str) -> Page:
        from apps.smallstack.crud import _apply_ordering_fields

        qs: QuerySet = ds.queryset(request, filters)
        if ordering:
            qs = _apply_ordering_fields(qs, ordering, set(ds.column_names()))
        if not qs.ordered:
            qs = qs.order_by("-pk")  # stable paging for models with no Meta.ordering
        return paginate_queryset(qs, request, page_size=PAGE_SIZE)

    @staticmethod
    def _cells(obj: Any, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cells: list[dict[str, Any]] = []
        for col in columns:
            name, typ = col["name"], col["type"]
            value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
            if typ == "fk" and value is not None and not isinstance(value, (int, str)):
                value = str(value)
            cells.append({"name": name, "type": typ, "value": value})
        return cells

    # -- roll-up -------------------------------------------------------------

    @staticmethod
    def _rollup(
        request: HttpRequest,
        ds: Dataset,
        schema: dict[str, Any],
        declared: list[dict[str, Any]],
        filters: dict[str, str],
    ) -> dict[str, Any]:
        dimensions = [c for c in schema["columns"] if c["role"] == "dimension"]
        measures = [c for c in schema["columns"] if c["role"] == "measure"]
        group_by = request.GET.get("group_by", "").strip()
        measure = request.GET.get("measure", "").strip()
        agg = request.GET.get("agg", "count").strip() or "count"
        # Any real column can be grouped on (status codes are integers, hence
        # "measures", yet "requests by status" is the most natural roll-up).
        # Dimensions are listed first; declared ratio measures aren't groupable.
        groupable = [c for c in schema["columns"] if not c.get("computed")]
        valid_dims = {c["name"] for c in groupable}
        valid_measures = {c["name"] for c in measures}
        labels = {c["name"]: c["label"] for c in schema["columns"]}
        if measure not in valid_measures:
            measure = ""
        if agg not in dict(AGG_CHOICES):
            agg = "count"
        series: list[dict[str, Any]] = []
        series_error = ""
        if group_by in valid_dims:
            try:
                series = ds.series(
                    group_by,
                    measure=measure or None,
                    agg=agg if measure else "count",
                    limit=SERIES_LIMIT,
                    filters=filters,
                    request=request,
                )
            except ValueError as exc:
                series_error = str(exc)
            peak = max((float(s["value"]) for s in series if s["value"] is not None), default=0.0)
            for s in series:
                val = s["value"]
                s["pct"] = round(100 * float(val) / peak, 1) if peak and val is not None else 0
        else:
            group_by = ""
        measure_is_ratio = any(c["name"] == measure and c.get("computed") for c in measures)
        return {
            "dimensions": dimensions,
            "groupable_measures": [c for c in groupable if c["role"] == "measure"],
            "group_by_label": labels.get(group_by, group_by),
            "measure_label": labels.get(measure, measure),
            "measure_is_ratio": measure_is_ratio,
            "measures": measures,
            "declared_measures": declared,
            "agg_choices": AGG_CHOICES,
            "group_by": group_by,
            "measure": measure,
            "agg": agg,
            "series": series,
            "series_error": series_error,
        }

    # -- export --------------------------------------------------------------

    @staticmethod
    def _csv_url(key: str, enable_api: bool, filters: dict[str, str]) -> str:
        if not enable_api:
            return ""
        params = {**filters, "format": "csv"}
        return reverse("datasets:rows", kwargs={"key": key}) + "?" + urlencode(params)
