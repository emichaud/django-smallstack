"""The staff dataset browser — ``/smallstack/datasets/browse/``.

A thin, generic UI over the ``@dataset`` contract: the index lists every
registered dataset; the browse page builds its filter bar from
``schema()["filters"]``, its table from ``schema()["columns"]``, pages through
``queryset()`` and offers a one-dimension roll-up via ``series()``. It never
hard-codes a model or a column — the same page serves the bundled
``smallstack_*`` datasets and whatever a downstream project declares.

Besides the flat quick filters, the page takes ``?filter_tree=<json>`` — the
same nested AND/OR tree REST takes and a metric stores — drawn by the shared
editor (datasets/js/filter-tree.js) under **More conditions** and AND-ed with
the quick filters. A tree that can't be applied shows its problem and **no
rows**, never the unfiltered set (a dropped condition is the fail-open shape).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.core.paginator import Page
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.views.generic import TemplateView

from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.pagination import PAGE_SIZE_CHOICES, paginate_queryset
from apps.smallstack.sorting import build_sort_headers

from .core import Dataset, get_dataset, list_datasets
from .filter_tree import and_trees, describe_filter_tree, is_empty
from .framework import is_framework_dataset
from .registry import get_def, user_may_view_model

#: The quick date presets (``_computed_filter_meta`` / the CRUD list pipeline)
#: as the relative periods a filter tree takes, for "Save as metric".
#: The quick date presets as the periods that cover exactly the same days
#: (the CRUD pipeline applies the presets; filter_tree the periods), so a
#: metric made from the browser counts what the browser showed.
_PRESET_PERIODS = {
    "today": "today",
    "yesterday": "yesterday",
    "week": "last_7",
    "month": "this_month",
    "year": "this_year",
}
#: Card types a grouped roll-up can be kept as, in the order offered. Pie
#: takes a count or sum only (a share of an average means nothing).
_ROLLUP_CARDS = (("metric_group", "Grouped stat"), ("ranked", "Ranked bars"), ("pie", "Pie chart"))
_ADDITIVE_AGGS = frozenset({"count", "sum"})

#: Browse page sizes (rows per page, ``?per_page=``) — SmallStack's list
#: choices, so this page pages like every CRUD list; the first is the default.
PAGE_SIZES = PAGE_SIZE_CHOICES
PAGE_SIZE = PAGE_SIZES[0]
#: Index page sizes (datasets per section) — the browse page's, so both pages page alike.
INDEX_PAGE_SIZES = PAGE_SIZES
SERIES_LIMIT = 50
AGG_CHOICES = (("count", "Count"), ("sum", "Sum"), ("avg", "Average"), ("min", "Min"), ("max", "Max"))

#: Query params the browse page owns; everything else is a dataset filter.
_PAGE_PARAMS = {"ordering", "page", "per_page", "group_by", "measure", "agg", "filter_tree", "metric"}


class DatasetIndexView(StaffRequiredMixin, TemplateView):
    template_name = "datasets/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request
        framework: list[dict[str, Any]] = []
        project: list[dict[str, Any]] = []
        for entry in list_datasets():
            ds = get_dataset(entry["key"])
            dfn = get_def(entry["key"])
            if ds is None or dfn is None or not user_may_view_model(dfn, request.user):
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

        per_page = _int_in(request.GET.get("per_page"), INDEX_PAGE_SIZES, INDEX_PAGE_SIZES[0])
        framework_page = paginate_queryset(framework, request, page_size=per_page, page_param="fpage")
        project_page = paginate_queryset(project, request, page_size=per_page, page_param="ppage")
        # Both sections page in place with the framework pager, each under its
        # own page param; one "Rows per page" sets both (see index.html).
        context.update(
            {
                "framework_datasets": framework,
                "project_datasets": project,
                "framework_page": framework_page,
                "project_page": project_page,
                "per_page": per_page,
                "page_sizes": INDEX_PAGE_SIZES,
                "total": len(framework) + len(project),
            }
        )
        return context


def _int_in(raw: Any, allowed: tuple[int, ...], default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value in allowed else default


class DatasetBrowseView(StaffRequiredMixin, TemplateView):
    template_name = "datasets/browse.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        dfn = get_def(kwargs["key"])
        if dfn is not None and not user_may_view_model(dfn, request.user):
            raise PermissionDenied("You need the view permission on this dataset's model.")
        # "Start from a metric" without JavaScript sends ?metric=<key> alone:
        # load it, as the picked option's address does.
        if set(request.GET) == {"metric"}:
            ds = get_dataset(kwargs["key"])
            if ds is not None:
                for m in self._saved_metrics(request, ds)["saved_metrics"]:
                    if m["current"] and m["url"] != request.get_full_path():
                        return redirect(m["url"])
        return super().get(request, *args, **kwargs)

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
        tree, tree_error = self._tree(request, ds)
        # A bound that won't parse (a typed "2026-13-45") is shown, not dropped:
        # dropping it would list more rows than the filters on screen say.
        problems = ds.filter_problems(filters)
        filter_error = ("These filters can't be applied: " + "; ".join(problems) + ".") if problems else ""
        blocked = bool(tree_error or filter_error)  # show nothing rather than every row
        ordering = request.GET.get("ordering", "").strip()
        per_page = _int_in(request.GET.get("per_page"), PAGE_SIZES, PAGE_SIZE)
        page_obj = self._page(request, ds, filters, tree, ordering, per_page, none=blocked)

        rows = [{"url": ds.link_for(obj), "cells": self._cells(obj, columns)} for obj in page_obj.object_list]
        headers = build_sort_headers([(c["name"], c["label"]) for c in columns], ordering)
        for header, col in zip(headers, columns):
            header["type"] = col["type"]
        labels = {c["name"]: c["label"] for c in schema["columns"]}

        context.update(
            {
                "dataset": ds,
                "dfn": dfn,
                "schema": schema,
                "columns": columns,
                "headers": headers,
                "ordering": ordering,
                "widgets": self._widgets(schema, request),
                "filters": filters,
                "has_filters": bool(filters) or tree is not None or blocked,
                # The tree as the hidden input carries it (compact JSON) and as words.
                "tree_json": json.dumps(tree, separators=(",", ":")) if tree is not None else "",
                "tree_error": tree_error,
                "filter_error": filter_error,
                "blocked": blocked,
                "tree_reading": describe_filter_tree(tree, labels) if tree is not None and not tree_error else "",
                "page_obj": page_obj,
                "per_page": per_page,
                "page_sizes": PAGE_SIZES,
                "rows": rows,
                "has_links": ds.has_links(),
                "csv_url": "" if blocked else self._csv_url(key, dfn.enable_api, filters, tree),
                "is_framework": is_framework_dataset(key),
                **self._rollup(request, ds, schema, declared, filters, tree, skip=blocked),
            }
        )
        context.update(self._keep_links(ds, schema, filters, tree, context, blocked=blocked))
        context.update(self._saved_metrics(request, ds))
        loaded = context["loaded_metric"]
        if loaded is not None and context["metric_url"]:
            # Started from a saved metric: Make a metric is a copy of it, with
            # whatever the conditions are now (MetricQuickView reads from=).
            copy = {
                "from": loaded.key,
                "name": f"{loaded.name} (copy)"[:120],
                "period_field": loaded.period_field,
                "format": loaded.format,
            }
            context["metric_url"] += "&" + urlencode(copy)
        return context

    @staticmethod
    def _saved_metrics(request: HttpRequest, ds: Dataset) -> dict[str, Any]:
        """The metrics already made on this dataset, to start from: each with the
        browse address that loads its conditions (``filter_tree``) and roll-up
        (``agg``/``measure``), marked by ``?metric=<key>``. ``loaded_metric`` is
        the one the page was started from (it stays in the form as the filters
        change). Nothing without the dashboards app."""
        from django.apps import apps as django_apps

        out: dict[str, Any] = {"saved_metrics": [], "loaded_metric": None}
        if not django_apps.is_installed("apps.dashboards"):
            return out
        from apps.dashboards.models import Metric

        wanted = request.GET.get("metric", "").strip()
        base = reverse("datasets:browse", args=[ds.key])
        rows = Metric.objects.visible_to(request.user).active().filter(source="dataset", dataset=ds.key)
        for metric in rows.order_by("name"):
            params = {"metric": metric.key}
            if not is_empty(metric.filter_tree):
                params["filter_tree"] = json.dumps(metric.filter_tree, separators=(",", ":"))
            if metric.measure:
                params.update(measure=metric.measure, agg=metric.agg)
            current = metric.key == wanted
            out["saved_metrics"].append(
                {"key": metric.key, "name": metric.name, "url": f"{base}?{urlencode(params)}", "current": current}
            )
            if current:
                out["loaded_metric"] = metric
        return out

    # -- keep it: save the filtered rows as a metric, the roll-up as a card ----

    @classmethod
    def _keep_links(
        cls,
        ds: Dataset,
        schema: dict[str, Any],
        filters: dict[str, str],
        tree: Any,
        rollup: dict[str, Any],
        *,
        blocked: bool,
    ) -> dict[str, Any]:
        """Links into the dashboards app that carry what's on screen: **Make a
        metric** (the dataset, every condition as one filter tree, the roll-up's
        aggregate — the modal form, ``dashboards_metric_quick``) and, for a
        grouped roll-up, **keep as a card** (the same metric, then a grouped
        card by the group-by column). Nothing when the dashboards app isn't
        installed, the tree can't be applied, or the quick filters can't be
        said as a tree (then it says why rather than offering a metric that's
        wider than the table)."""
        from django.apps import apps as django_apps

        out: dict[str, Any] = {"metric_url": "", "card_links": [], "keep_problem": ""}
        if blocked or not django_apps.is_installed("apps.dashboards"):
            return out
        try:
            create_url = reverse("dashboards_metric_quick")
        except NoReverseMatch:
            return out
        combined = and_trees(cls._tree_from_quick_filters(schema, filters), tree)
        if not is_empty(combined):
            problems = ds.validate_filter_tree(combined)
            if problems:
                out["keep_problem"] = "The quick filters can't be kept as a metric: " + "; ".join(problems)
                return out
        measure = rollup.get("measure") or ""
        params: dict[str, str] = {"dataset": ds.key}
        if not is_empty(combined):
            params["filter_tree"] = json.dumps(combined, separators=(",", ":"))
        # The roll-up's aggregate only means something over a measure; without
        # one the table (and so the metric) counts rows, as the roll-up does.
        params["agg"] = (rollup.get("agg") or "count") if measure else "count"
        if measure:
            params["measure"] = measure
        out["metric_url"] = create_url + "?" + urlencode(params)
        group_by = rollup.get("group_by") or ""
        if group_by:
            from apps.dashboards.components import get_component_type

            for type_key, label in _ROLLUP_CARDS:
                if get_component_type(type_key) is None:
                    continue
                if type_key == "pie" and params["agg"] not in _ADDITIVE_AGGS:
                    continue
                card = {**params, "then": "card", "card_type": type_key, "dimension": group_by}
                out["card_links"].append({"type": type_key, "label": label, "url": create_url + "?" + urlencode(card)})
        if out["card_links"]:
            out["sketch"] = cls._sketch(rollup.get("series") or [])
        return out

    @staticmethod
    def _sketch(series: list[dict[str, Any]]) -> dict[str, Any]:
        """The roll-up on screen drawn small, one way per card type, so each
        keep-as-card choice shows what it would make: the total with its
        largest groups (a grouped stat), bars largest first (ranked bars), and
        the shares as a conic gradient (a pie), the accent fading from the
        largest slice down. Theme tokens only, so it holds on every palette."""
        valued = sorted(
            ((str(s["label"]), float(s["value"])) for s in series if s.get("value") is not None),
            key=lambda lv: lv[1],
            reverse=True,
        )
        total = sum(v for _, v in valued)
        peak = valued[0][1] if valued else 0.0

        def _num(v: float) -> str:
            return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"

        strengths = (90, 62, 42, 28, 18, 12)
        stops: list[str] = []
        at = 0.0
        for i, (_label, v) in enumerate(valued[: len(strengths)]):
            share = 100 * v / total if total else 0.0
            tint = f"color-mix(in srgb, var(--primary) {strengths[i]}%, var(--card-bg))"
            stops.append(f"{tint} {at:.1f}% {at + share:.1f}%")
            at += share
        if at < 99.95:
            stops.append(f"color-mix(in srgb, var(--body-fg) 10%, var(--card-bg)) {at:.1f}% 100%")
        return {
            "total": _num(total),
            "groups": [{"label": label, "value": _num(v)} for label, v in valued[:2]],
            "bars": [{"label": label, "pct": round(100 * v / peak) if peak else 0} for label, v in valued[:4]],
            "pie": "conic-gradient(" + ", ".join(stops) + ")" if stops else "",
        }

    @staticmethod
    def _tree_from_quick_filters(schema: dict[str, Any], filters: dict[str, str]) -> Any:
        """The quick filters as filter-tree leaves, so a metric keeps *every*
        condition the table had: a text box is ``contains``, a choice ``=``, a
        date preset a relative ``period``, and ``<col>__gte`` / ``__lt`` the
        bounds. Mirrors how the flat filters apply (core._filtered_qs)."""
        meta = {w["name"]: w for w in schema.get("filters", [])}
        # An explicit bound on a column drops that column's preset (as the flat
        # filters apply it: explicit wins), so the tree says the same thing.
        ranged = {n.partition("__")[0] for n in filters if n.partition("__")[2] in ("gte", "lt")}
        leaves: list[dict[str, Any]] = []
        for name, raw in filters.items():
            base, sep, lookup = name.partition("__")
            if sep and lookup in ("gte", "lt"):
                leaves.append({"field": base, "op": ">=" if lookup == "gte" else "<", "value": raw})
                continue
            w = meta.get(name)
            if w is None or name in ranged:
                continue
            if w.get("type") == "text":
                leaves.append({"field": name, "op": "contains", "value": raw})
            elif w.get("is_date") or w.get("range"):
                leaves.append({"field": name, "op": "period", "value": _PRESET_PERIODS.get(raw, raw)})
            else:
                leaves.append({"field": name, "op": "=", "value": raw})
        return {"and": leaves} if len(leaves) > 1 else (leaves[0] if leaves else {})

    # -- filters -------------------------------------------------------------

    @staticmethod
    def _tree(request: HttpRequest, ds: Dataset) -> tuple[Any, str]:
        """``?filter_tree=<json>`` → ``(tree, problem)``. ``(None, "")`` when
        absent or empty. A tree with a problem comes back as ``(tree, why)``
        so the page can keep it in the editor for fixing while applying
        nothing — the caller shows no rows, not all of them."""
        raw = request.GET.get("filter_tree", "").strip()
        if not raw:
            return None, ""
        try:
            tree = json.loads(raw)
        except ValueError as exc:
            return None, f"The conditions aren't valid JSON: {exc}"
        if is_empty(tree):
            return None, ""
        problems = ds.validate_filter_tree(tree)
        if problems:
            return tree, "These conditions can't be applied: " + "; ".join(problems)
        return tree, ""

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
    def _page(
        request: HttpRequest,
        ds: Dataset,
        filters: dict[str, str],
        tree: Any,
        ordering: str,
        per_page: int,
        *,
        none: bool = False,
    ) -> Page:
        from apps.smallstack.crud import _apply_ordering_fields

        # A tree that can't be applied isn't compiled at all (it would raise); the
        # page shows nothing for it rather than everything.
        qs: QuerySet = ds.queryset(request, {} if none else filters, filter_tree=None if none else tree)
        if none:
            qs = qs.none()
        if ordering:
            qs = _apply_ordering_fields(qs, ordering, set(ds.column_names()))
        if not qs.ordered:
            qs = qs.order_by("-pk")  # stable paging for models with no Meta.ordering
        return paginate_queryset(qs, request, page_size=per_page)

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
        tree: Any = None,
        *,
        skip: bool = False,
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
        if group_by in valid_dims and skip:
            pass  # the tree can't be applied: no roll-up either, rather than one over every row
        elif group_by in valid_dims:
            try:
                series = ds.series(
                    group_by,
                    measure=measure or None,
                    agg=agg if measure else "count",
                    limit=SERIES_LIMIT,
                    filters=filters,
                    request=request,
                    filter_tree=tree,
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
    def _csv_url(key: str, enable_api: bool, filters: dict[str, str], tree: Any = None) -> str:
        if not enable_api:
            return ""
        params = {**filters, "format": "csv"}
        if tree is not None:
            params["filter_tree"] = json.dumps(tree, separators=(",", ":"))
        return reverse("datasets:rows", kwargs={"key": key}) + "?" + urlencode(params)
