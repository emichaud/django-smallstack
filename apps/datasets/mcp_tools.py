"""Register dataset MCP tools.

Exposes each ``enable_mcp`` dataset as a ``query_dataset_<key>`` tool (rows, or
a grouped series when ``group_by`` is passed), plus a site-level
``list_datasets`` tool. Mirrors ``apps/search/mcp_tools.py``: a full run
registers everything present and subscribes an ``add_register_hook`` so datasets
declared after this app's ready() self-expose (INSTALLED_APPS-order independent).

Guarded so that if ``apps.mcp`` isn't installed (or MCP is off site-wide) this
is a silent no-op — the REST + in-process surfaces still work.
"""

from __future__ import annotations

import logging
from typing import Any

from django.http import HttpRequest, QueryDict

from .registry import DatasetDef, all_defs

logger = logging.getLogger(__name__)

_RESERVED = {
    "ordering",
    "limit",
    "offset",
    "group_by",
    "group_by2",
    "sort",
    "scalar",
    "measure",
    "agg",
    "buckets",
    "auto",
    "auto_limit",
    "label_field",
    "bucket",
    "filter_tree",
}


def _tool_name(key: str) -> str:
    return f"query_dataset_{key}"


def _bucket_dimension(field: str, args: dict) -> dict | None:
    """Build a bucketed-dimension dict from tool args, or None for raw grouping.

    ``buckets`` (a JSON array of bucket objects) or ``auto`` (bool, with optional
    ``auto_limit``/``label_field``) turn ``field`` into a bucketed dimension.
    """
    if not field:
        return None
    raw_buckets = args.get("buckets")
    auto = bool(args.get("auto"))
    if not raw_buckets and not auto:
        return None
    dim: dict = {"field": field}
    if raw_buckets:
        dim["buckets"] = raw_buckets  # MCP args are JSON — already a list of dicts
    elif auto:
        opts: dict = {}
        if args.get("auto_limit"):
            opts["limit"] = args["auto_limit"]
        if args.get("label_field"):
            opts["label_field"] = args["label_field"]
        dim["auto"] = opts or True
    return dim


#: Tool-argument help for each explicit lookup suffix (``core._LOOKUPS_BY_TYPE``).
_LOOKUP_HELP = {
    "gte": "{name} at or above this value (dates: ISO, inclusive).",
    "gt": "{name} above this value.",
    "lte": "{name} at or below this value.",
    "lt": "{name} below this value (dates: ISO, exclusive).",
    "period": "{name} within a relative period: today, yesterday, wtd, mtd, qtd, ytd, last_<N>, … "
    "(describe_dataset lists them).",
    "ne": "{name} is not this value (rows without one are kept).",
    "icontains": "{name} contains this text (case-insensitive).",
}


def _input_schema(dfn: DatasetDef) -> dict[str, Any]:
    """JSON Schema for a dataset tool. Filter field names are derived DB-free."""
    from .core import _AGG_NAMES, _LOOKUPS_BY_TYPE, Dataset

    props: dict[str, Any] = {}
    declared_measures: list[str] = []
    try:
        ds = Dataset(dfn)
        types = ds.filter_column_types()
        for fname in ds.filter_field_names():
            props[fname] = {"type": "string", "description": f"Filter by {fname}."}
        # The explicit lookups each column's type takes, alongside its bare key.
        for fname in ds.filter_field_names():
            for lookup in _LOOKUPS_BY_TYPE.get(types.get(fname, ""), ()):
                props[f"{fname}__{lookup}"] = {
                    "type": "string",
                    "description": _LOOKUP_HELP[lookup].format(name=fname),
                }
        declared_measures = list(ds.declared_measures())
    except Exception:
        # A dataset whose queryset can't be constructed at startup still gets a
        # usable (filter-less) tool rather than none.
        logger.exception("dataset %s: could not derive filter fields", dfn.key)

    props["filter_tree"] = {
        "type": "object",
        "description": (
            "Nested AND/OR filter, AND-ed with the flat filter args: "
            '{"and": [{"field": "status", "op": "=", "value": "open"}, '
            '{"or": [...]}, {"field": "created_at", "op": "period", "value": "mtd"}]}. '
            "Ops: = != > >= < <= between(value,value2) in(list) contains isnull period. "
            "Call describe_dataset for each field's ops and the period keys."
        ),
    }
    props["group_by"] = {
        "type": "string",
        "description": "Return a grouped series ([{label, value}]) by this dimension instead of rows.",
    }
    props["group_by2"] = {
        "type": "string",
        "description": (
            "With group_by, a second dimension: return a complete grid "
            "[{x, x_label, y, y_label, value}] (a heatmap) instead of a series. "
            "Each axis takes at most 30 distinct values."
        ),
    }
    props["sort"] = {
        "type": "string",
        "enum": ["category", "-category", "value", "-value"],
        "description": (
            "Series order (default category: the dimension's order). value/-value ranks by the "
            "aggregate before limit applies, so -value with limit N is a top N."
        ),
    }
    props["buckets"] = {
        "type": "array",
        "description": (
            "With group_by, bucket the field (count-only) instead of grouping raw "
            "values. Each item: {key, label} plus one of {lo, hi} (numeric [lo,hi), "
            "hi omitted = open-ended), {value} (equals), {values:[…]} (in-group), or "
            "{other: true} (the complement of the listed values)."
        ),
        "items": {"type": "object"},
    }
    props["auto"] = {
        "type": "boolean",
        "description": "With group_by, auto-derive top-N value buckets (+ 'other') from the data.",
    }
    props["auto_limit"] = {
        "type": "integer",
        "minimum": 1,
        "description": "Max auto buckets before the rest fold into 'other' (default 12).",
    }
    props["label_field"] = {
        "type": "string",
        "description": "Column to label auto buckets by (else the value itself).",
    }
    props["bucket"] = {
        "type": "string",
        "description": "Rows mode: drill into one bucket's rows (its key from a bucketed series).",
    }
    props["scalar"] = {
        "type": "boolean",
        "description": (
            "Return a single KPI number (one ungrouped aggregate, no group_by) "
            "using measure + agg. Ignored when group_by is set."
        ),
    }
    measure_desc = "Numeric column to aggregate for a series/scalar (omit to count rows)."
    if declared_measures:
        measure_desc += (
            " Declared ratio measures (computed sum/sum, agg ignored): " + ", ".join(declared_measures) + "."
        )
    props["measure"] = {"type": "string", "description": measure_desc}
    props["agg"] = {
        "type": "string",
        "enum": list(_AGG_NAMES),
        "description": "Aggregation for the series/scalar (default count).",
    }
    props["ordering"] = {
        "type": "string",
        "description": "Comma-separated field names; prefix with '-' for descending.",
    }
    props["limit"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 500,
        "default": 50,
        "description": "Max rows/series points to return.",
    }
    props["offset"] = {
        "type": "integer",
        "minimum": 0,
        "default": 0,
        "description": "Row offset for paging (rows mode only).",
    }
    return {"type": "object", "properties": props, "additionalProperties": False}


def _build_query_tool(tool: Any, dfn: DatasetDef) -> None:
    def handler(args: dict[str, Any], *, _key: str = dfn.key) -> dict[str, Any]:
        from apps.mcp.server import current_context

        from .core import get_dataset
        from .registry import get_def, user_may_view_model

        ds = get_dataset(_key)
        dfn_now = get_def(_key)
        ctx = current_context()
        if ds is None or dfn_now is None or not user_may_view_model(dfn_now, getattr(ctx, "user", None)):
            return {"error": f"dataset '{_key}' not found"}

        request = _fake_context_request(getattr(ctx, "user", None))

        # Non-reserved args are filters — applied identically across rows,
        # series and scalar so the same filter contract holds in every mode.
        filters = {k: v for k, v in args.items() if k not in _RESERVED and v not in (None, "")}

        filter_tree = args.get("filter_tree") or None
        group_by = (args.get("group_by") or "").strip()
        # A bucketed dimension: group_by is the field, buckets/auto define the
        # bands → count-only [{key, label, value, lo, hi}].
        dimension = _bucket_dimension(group_by, args)
        group_by2 = (args.get("group_by2") or "").strip()
        if group_by and group_by2:
            try:
                cells = ds.cells(
                    group_by,
                    group_by2,
                    measure=(args.get("measure") or None),
                    agg=(args.get("agg") or "count"),
                    filters=filters,
                    request=request,
                    filter_tree=filter_tree,
                )
            except ValueError as exc:
                return {"error": str(exc)}
            return {"key": _key, "mode": "cells", "count": len(cells), "cells": cells}
        if group_by:
            raw_sort = (args.get("sort") or "").strip()
            sort = (
                {"by": raw_sort.lstrip("-"), "dir": "desc" if raw_sort.startswith("-") else "asc"} if raw_sort else None
            )
            try:
                series = ds.series(
                    dimension if dimension is not None else group_by,
                    measure=(args.get("measure") or None),
                    agg=(args.get("agg") or "count"),
                    sort=sort,
                    limit=args.get("limit") or 50,
                    filters=filters,
                    request=request,
                    filter_tree=filter_tree,
                )
            except ValueError as exc:
                return {"error": str(exc)}
            return {"key": _key, "mode": "series", "count": len(series), "series": series}

        if args.get("scalar"):
            try:
                value = ds.scalar(
                    measure=(args.get("measure") or None),
                    agg=(args.get("agg") or "count"),
                    filters=filters,
                    request=request,
                    filter_tree=filter_tree,
                )
            except ValueError as exc:
                return {"error": str(exc)}
            return {
                "key": _key,
                "mode": "scalar",
                "agg": args.get("agg") or "count",
                "measure": args.get("measure") or None,
                "value": value,
            }

        # Expand every FK column so an agent sees names, not opaque pks.
        # ``bucket`` (+ the group_by/buckets/auto that define the dimension)
        # narrows to one bucket's rows — the drilldown behind a chart segment.
        bucket = (args.get("bucket") or "").strip() or None
        try:
            rows = ds.rows(
                filters=filters,
                ordering=(args.get("ordering") or ""),
                limit=args.get("limit") or 50,
                offset=args.get("offset") or 0,
                expand=sorted(ds.fk_column_names()),
                dimension=dimension if bucket else None,
                bucket=bucket,
                request=request,
                filter_tree=filter_tree,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        return {"key": _key, "mode": "rows", "count": len(rows), "results": rows}

    desc = (
        f"Query the '{dfn.label}' dataset. {dfn.description} "
        "Returns typed rows, or a grouped [{label, value}] series when group_by is set. "
        "Apply the filter args to reduce the rows. "
        "A row's 'url' (when present) is the page where that record can be viewed."
    ).strip()
    tool(
        _tool_name(dfn.key),
        desc,
        _input_schema(dfn),
        requires_access=dfn.mcp_access,
    )(handler)


def _fake_context_request(user: Any) -> HttpRequest:
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict("", mutable=False)
    req.META = {}
    return req


def _late_hook(dfn: DatasetDef) -> None:
    if getattr(dfn, "enable_mcp", False):
        register_dataset_tools(only_def=dfn)


def register_dataset_tools(only_def: DatasetDef | None = None) -> int:
    """Register dataset MCP tools. Called from DatasetsConfig.ready().

    With ``only_def`` set, registers just that dataset's tool (the late hook).
    Returns the number of tools registered.
    """
    try:
        from apps.mcp.server import tool
    except Exception:
        logger.info("apps.mcp not available — skipping dataset MCP tools")
        return 0

    count = 0
    defs = [only_def] if only_def is not None else list(all_defs())
    for dfn in defs:
        if not getattr(dfn, "enable_mcp", False):
            continue
        try:
            _build_query_tool(tool, dfn)
            count += 1
        except Exception:
            logger.exception("Failed to register MCP tool for dataset %s", dfn.key)

    # Per-dataset work done; the late hook stops here (list_datasets is
    # site-level and registered once on the full run).
    if only_def is not None:
        return count

    from .registry import add_register_hook

    add_register_hook(_late_hook)

    try:
        tool(
            "list_datasets",
            (
                "List the datasets you may read on this site — each is a named, filterable "
                "table of rows and columns, and what a metric is built on. Returns {key, label, "
                "description, query_tool}. Use a key with describe_dataset and metric_preview; "
                "query_tool names its query_dataset_<key> tool for pulling rows, or is null when "
                "this site doesn't publish one (metrics still work)."
            ),
            {"type": "object", "properties": {}, "additionalProperties": False},
            requires_access="readonly",
        )(_list_datasets_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register list_datasets MCP tool")

    try:
        tool(
            "describe_dataset",
            (
                "Describe one dataset before querying it or building a metric on it: typed "
                "columns (dimension vs measure), every filterable field with the filter_tree "
                "ops it accepts (and the relative period keys for date fields), the "
                "aggregations, and its capabilities. Input: {key}."
            ),
            {
                "type": "object",
                "properties": {"key": {"type": "string", "description": "A dataset key from list_datasets."}},
                "required": ["key"],
                "additionalProperties": False,
            },
            requires_access="readonly",
        )(_describe_dataset_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register describe_dataset MCP tool")

    return count


def caller_may_use(dfn: DatasetDef) -> bool:
    """Whether the current MCP caller clears *dfn*'s ``mcp_access`` tier — the
    same gate its ``query_dataset_<key>`` tool enforces. Site-level tools that
    take a dataset key (describe_dataset, the dashboards metric tools) call
    this so a key can't reach a dataset its own tool would refuse."""
    from apps.mcp.auth import check_tool_access
    from apps.mcp.server import ToolDef, current_context

    from .registry import user_may_view_model

    ctx = current_context()
    token = getattr(ctx, "token", None)
    user = getattr(ctx, "user", None)
    if not user_may_view_model(dfn, user):
        return False
    if token is not None:
        probe = ToolDef(name=_tool_name(dfn.key), description="", input_schema={}, requires_access=dfn.mcp_access)
        return check_tool_access(token, probe) is None
    # In-process (no token): fall back to the user's live flags.
    if dfn.mcp_access == "staff":
        return bool(getattr(user, "is_staff", False))
    return bool(getattr(user, "is_authenticated", False))


def _describe_dataset_handler(args: dict) -> dict[str, Any]:
    from .core import get_dataset
    from .registry import get_def

    key = str(args.get("key") or "")
    dfn = get_def(key)
    ds = get_dataset(key) if dfn is not None and _caller_may_read(dfn) else None
    if ds is None:
        return {"error": f"unknown dataset {key!r} — use list_datasets"}
    return ds.schema()


def _list_datasets_handler(args: dict) -> dict[str, Any]:
    """Every dataset the caller may read — the rule ``metric_preview`` and
    ``create_metric`` apply. ``enable_mcp`` decides whether a dataset gets its own
    ``query_dataset_<key>`` tool, not whether an agent may know it exists: gating
    this list on it hid all the bundled datasets from a metric-building agent
    (their tools are off by default) while those tools went on accepting them."""
    from .core import list_datasets
    from .registry import get_def

    items = []
    for d in list_datasets():
        dfn = get_def(d["key"])
        if dfn is None or not _caller_may_read(dfn):
            continue
        queryable = dfn.enable_mcp and caller_may_use(dfn)
        items.append(
            {
                "key": d["key"],
                "label": d["label"],
                "description": d["description"],
                "query_tool": _tool_name(dfn.key) if queryable else None,
            }
        )
    return {"results": items}


def _caller_may_read(dfn: DatasetDef) -> bool:
    from apps.mcp.server import current_context

    from .registry import user_may_read, user_may_view_model

    user = getattr(current_context(), "user", None)
    return user_may_read(dfn, user) or (dfn.enable_mcp and caller_may_use(dfn) and user_may_view_model(dfn, user))
