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

logger = logging.getLogger("smallstack.datasets")

_RESERVED = {
    "ordering", "limit", "offset", "group_by", "scalar", "measure", "agg",
    "buckets", "auto", "auto_limit", "label_field", "bucket",
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


def _input_schema(dfn: DatasetDef) -> dict[str, Any]:
    """JSON Schema for a dataset tool. Filter field names are derived DB-free."""
    from .core import Dataset

    props: dict[str, Any] = {}
    declared_measures: list[str] = []
    try:
        ds = Dataset(dfn)
        cols = dict(ds.columns())
        date_cols = set()
        for fname in ds.filter_field_names():
            props[fname] = {"type": "string", "description": f"Filter by {fname}."}
            if cols.get(fname) in ("date", "datetime"):
                date_cols.add(fname)
        # Explicit half-open date bounds alongside the bare-column preset.
        for fname in date_cols:
            props[f"{fname}__gte"] = {
                "type": "string",
                "description": f"{fname} on/after this ISO date/datetime (inclusive).",
            }
            props[f"{fname}__lt"] = {
                "type": "string",
                "description": f"{fname} before this ISO date/datetime (exclusive).",
            }
        declared_measures = list(ds.declared_measures())
    except Exception:
        # A dataset whose queryset can't be constructed at startup still gets a
        # usable (filter-less) tool rather than none.
        logger.exception("dataset %s: could not derive filter fields", dfn.key)

    props["group_by"] = {
        "type": "string",
        "description": "Return a grouped series ([{label, value}]) by this dimension instead of rows.",
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
            " Declared ratio measures (computed sum/sum, agg ignored): "
            + ", ".join(declared_measures)
            + "."
        )
    props["measure"] = {"type": "string", "description": measure_desc}
    props["agg"] = {
        "type": "string",
        "enum": ["count", "sum", "avg", "min", "max"],
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

        ds = get_dataset(_key)
        if ds is None:
            return {"error": f"dataset '{_key}' not found"}

        ctx = current_context()
        request = _fake_context_request(getattr(ctx, "user", None))

        # Non-reserved args are filters — applied identically across rows,
        # series and scalar so the same filter contract holds in every mode.
        filters = {
            k: v for k, v in args.items() if k not in _RESERVED and v not in (None, "")
        }

        group_by = (args.get("group_by") or "").strip()
        # A bucketed dimension: group_by is the field, buckets/auto define the
        # bands → count-only [{key, label, value, lo, hi}].
        dimension = _bucket_dimension(group_by, args)
        if group_by:
            try:
                series = ds.series(
                    dimension if dimension is not None else group_by,
                    measure=(args.get("measure") or None),
                    agg=(args.get("agg") or "count"),
                    limit=args.get("limit") or 50,
                    filters=filters,
                    request=request,
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
                "List the datasets available to query on this site — each is a named, "
                "filterable table of rows and columns. Returns {key, label, description}. "
                "Use a key with query_dataset_<key> to pull rows or a grouped series."
            ),
            {"type": "object", "properties": {}, "additionalProperties": False},
            requires_access="readonly",
        )(_list_datasets_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register list_datasets MCP tool")

    return count


def _list_datasets_handler(args: dict) -> dict[str, Any]:
    from .core import list_datasets

    # MCP surface advertises only the MCP-exposed datasets.
    items = [
        {"key": d["key"], "label": d["label"], "description": d["description"]}
        for d in list_datasets()
        if _is_mcp(d["key"])
    ]
    return {"results": items}


def _is_mcp(key: str) -> bool:
    from .registry import get_def

    dfn = get_def(key)
    return bool(dfn and getattr(dfn, "enable_mcp", False))
