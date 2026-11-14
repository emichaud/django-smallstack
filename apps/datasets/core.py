"""The Dataset wrapper: schema / rows / series over a registered queryset.

Everything here is *composed* from the existing CRUDView list pipeline — it does
not reinvent filtering, serialization, or type derivation:

- typed columns  → ``_model_field_type`` (api.py) + ``_build_filter_meta`` (crud.py)
- sub-filtering  → ``apply_filters`` (crud.py, the dependency-free path MCP reuses)
- ordering       → ``apply_ordering`` (crud.py)
- row → dict     → ``serialize`` (api.py)
- series rollup  → ``qs.values(dim).annotate(agg)`` (same idea as _compute_aggregations)

A ``Dataset`` isn't a CRUDView, so a small adapter (``_ConfigAdapter``) presents
exactly the ``crud_config`` interface those helpers expect (``.model``,
``_resolve_filter_fields``, ``_resolve_search_fields``, ``_get_list_fields``).
This is the same trick ``apps/mcp/factory.py`` uses to reuse the pipeline
outside HTTP.
"""

from __future__ import annotations

import csv
import inspect
import logging
import warnings
from typing import Any, Callable, Optional

from django.db.models import Aggregate, FloatField, Model, QuerySet
from django.db.models.functions import Cast
from django.http import HttpRequest, QueryDict

from .filter_tree import compile_filter_tree, is_empty, ops_for_type
from .registry import DatasetDef, all_defs, get_def

logger = logging.getLogger(__name__)

# Types the framework classifies as numeric → chartable "measures".
_MEASURE_TYPES = {"integer", "float", "decimal"}
_SERIES_LIMIT_MAX = 500
_ROWS_LIMIT_MAX = 500
_AGG_NAMES = ("count", "sum", "avg", "min", "max", "distinct", "median")
#: Aggregations whose value over no rows is 0 (the rest have no value: None).
_ZERO_WHEN_EMPTY = ("count", "distinct", "sum")
_DATE_TYPES = ("date", "datetime")

#: Per-axis cap for :meth:`Dataset.cells`. A grid is x × y cells, so cardinality
#: multiplies; 30 × 30 is already at the edge of readable. Past it ``cells()``
#: refuses, naming the field, rather than dropping part of an axis.
_CELLS_AXIS_MAX = 30

#: Explicit-lookup suffixes a flat filter key may carry (``<col>__<lookup>``),
#: by column type. Each is still one ``{name: scalar}`` key, so the flat filter
#: contract stays a serializable map (see the FILTER INVARIANT in _filtered_qs).
_COMPARISONS = ("gte", "gt", "lte", "lt")
_LOOKUPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "date": (*_COMPARISONS, "period"),
    "datetime": (*_COMPARISONS, "period"),
    "integer": _COMPARISONS,
    "float": _COMPARISONS,
    "decimal": _COMPARISONS,
    "string": ("ne", "icontains"),
}

#: The row key that carries the "view this object" URL (see Dataset.link_for).
LINK_KEY = "url"

_UNSET: Any = object()


def _agg_func(agg: str, measure: Optional[str]) -> Any:
    """Return the aggregate expression for ``agg`` over ``measure``.

    ``count`` (or a missing measure) counts rows; ``distinct`` counts distinct
    values of the measure column; the others aggregate the measure column.
    ``agg`` is assumed validated by the caller.
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    if agg == "distinct" and measure:
        return Count(measure, distinct=True)
    if agg in ("count", "distinct") or not measure:
        return Count("id")
    return {"sum": Sum, "avg": Avg, "min": Min, "max": Max, "median": Median}[agg](measure)


class Median(Aggregate):
    """The median of a numeric column, in the database, grouped or not.

    Postgres: ``percentile_cont(0.5)``. SQLite: a ``MEDIAN`` aggregate
    registered on each connection (:func:`install_sqlite_median`). Oracle has
    ``MEDIAN`` natively. Other backends refuse it up front
    (:func:`median_supported`) rather than fail inside a query.
    """

    function = "MEDIAN"
    name = "Median"
    output_field = FloatField()

    def __init__(self, expression: Any, **extra: Any) -> None:
        super().__init__(Cast(expression, FloatField()), **extra)

    def as_postgresql(self, compiler: Any, connection: Any, **extra_context: Any) -> Any:
        return self.as_sql(
            compiler,
            connection,
            template="percentile_cont(0.5) WITHIN GROUP (ORDER BY %(expressions)s)",
            **extra_context,
        )


_MEDIAN_VENDORS = ("postgresql", "sqlite", "oracle")


def median_supported(using: str = "default") -> bool:
    """True when the database behind *using* can compute :class:`Median`."""
    from django.db import connections

    return connections[using].vendor in _MEDIAN_VENDORS


class _SqliteMedian:
    """SQLite aggregate behind ``MEDIAN(x)``: NULLs skipped, None over no rows."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def step(self, value: Any) -> None:
        if value is not None:
            self.values.append(value)

    def finalize(self) -> Optional[float]:
        if not self.values:
            return None
        ordered = sorted(self.values)
        mid = len(ordered) // 2
        return float(ordered[mid]) if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def install_sqlite_median(sender: Any = None, connection: Any = None, **kwargs: Any) -> None:
    """``connection_created`` receiver: register ``MEDIAN`` on a SQLite connection."""
    if connection is not None and connection.vendor == "sqlite" and connection.connection is not None:
        connection.connection.create_aggregate("MEDIAN", 1, _SqliteMedian)


def csv_safe(value: Any) -> Any:
    """*value* for a CSV cell a spreadsheet will open: text a spreadsheet would
    run as a formula (``=cmd|…``, ``@SUM(…)``) gets a leading ``'``. Cells hold
    whatever people and requests wrote, and the person downloading isn't them.
    Plain numbers, negatives included, stay numbers."""
    if not isinstance(value, str) or value[:1] not in ("=", "+", "-", "@", "\t", "\r"):
        return value
    try:
        float(value)
    except ValueError:
        return f"'{value}"
    return value


class SafeCsvWriter:
    """``csv.writer`` with every cell through :func:`csv_safe`."""

    def __init__(self, out: Any) -> None:
        self._writer = csv.writer(out)

    def writerow(self, row: Any) -> None:
        self._writer.writerow([csv_safe(cell) for cell in row])

    def writerows(self, rows: Any) -> None:
        for row in rows:
            self.writerow(row)


def round_value(val: Any) -> Any:
    """An aggregate as shown: floats to 2 places, everything else as is."""
    return round(val, 2) if isinstance(val, float) else val


_round_value = round_value  # the name the series code uses


def _ratio_expr(spec: dict[str, Any]) -> Any:
    """DB expression for a declared ratio: ``sum(num) / sum(denom)`` (×100 for
    percent). ``NullIf(denom, 0)`` makes an empty-denominator group evaluate to
    NULL → None, so the ratio is recomputed from summed parts, never averaged."""
    from django.db.models import ExpressionWrapper, FloatField, Sum, Value
    from django.db.models.functions import Cast, NullIf

    mult = 100.0 if spec.get("fmt") == "percent" else 1.0
    return ExpressionWrapper(
        Cast(Sum(spec["num"]), FloatField()) * mult / NullIf(Sum(spec["denom"]), Value(0)),
        output_field=FloatField(),
    )


def _parse_date_bound(raw: Any) -> Any:
    """An ISO date or datetime string (or a date/datetime) for a comparison
    bound. None when unparseable; the caller refuses it (see _apply_lookup)."""
    from datetime import date, datetime

    if isinstance(raw, (date, datetime)):  # an in-process caller's own value
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_number(raw: Any, *, whole: bool = False) -> Any:
    """A numeric comparison bound (``<col>__gt=…``): int when integral, else
    float; None when unparseable. ``whole`` (an integer column) refuses a
    fraction, which the column would truncate (``__gte=1.5`` meaning ``>= 1``)."""
    try:
        text = str(raw).strip()
        value = float(text) if any(c in text.lower() for c in ".e") else int(text)
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if whole and isinstance(value, float):
        return None
    return value


def _infer_unit(name: str) -> Optional[str]:
    """A column's unit when ``@dataset(units=…)`` names none, from its name."""
    if name.endswith("_seconds"):
        return "seconds"
    if name.endswith("_minutes"):
        return "minutes"
    return None


def _sort_spec(sort: Optional[dict]) -> tuple[str, bool]:
    """``{"by": "category"|"value", "dir": "asc"|"desc"}`` → ``(by, descending)``.
    The default, category ascending, is the order a series always had."""
    spec = sort or {}
    by = spec.get("by") or "category"
    direction = spec.get("dir") or "asc"
    if by not in ("category", "value") or direction not in ("asc", "desc"):
        raise ValueError(f"unknown sort {spec!r}; by is category or value, dir is asc or desc")
    return by, direction == "desc"


def _fake_request(user: Any = None, query: str = "") -> HttpRequest:
    """Minimal request so the pipeline helpers can read ``.user`` / ``.GET``."""
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict(query, mutable=False)
    req.META = {}
    return req


#: Words a generated label keeps in capitals: "Ip address" reads as a typo.
_LABEL_ACRONYMS = {"api": "API", "id": "ID", "ip": "IP", "url": "URL", "uid": "UID", "uuid": "UUID", "http": "HTTP"}


def _label_for(model: type[Model], name: str) -> str:
    try:
        # get_field may return a reverse relation (ForeignObjectRel) with no
        # verbose_name — getattr falls through to the humanized name for those.
        field = model._meta.get_field(name)
        label = str(getattr(field, "verbose_name", name)).capitalize()
    except Exception:
        label = name.replace("_", " ").capitalize()
    return " ".join(_LABEL_ACRONYMS.get(word.lower(), word) for word in label.split(" "))


def _series_label(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ── date-dimension time bucketing ────────────────────────────────────────────
# Lifted verbatim from call_stats ``apps/datasets/core.py`` (like buckets.py):
# one grain grammar for both consumers — extend it here, don't fork it.
#
# Grouping a date/datetime dimension by its raw value yields one group per
# instant — never a trend. A `grain` truncates it to a calendar bucket (the
# native Django Trunc* — exact, calendar-aligned) so a bar/line reads as a time
# series. Only calendar units: an N-week bin isn't a calendar unit (it needs an
# epoch anchor) and isn't offered.
def _grain_truncs() -> dict[str, Any]:
    from django.db.models.functions import TruncDay, TruncMonth, TruncQuarter, TruncWeek, TruncYear

    return {
        "day": TruncDay,
        "week": TruncWeek,  # Django weeks start Monday
        "month": TruncMonth,
        "quarter": TruncQuarter,
        "year": TruncYear,
    }


GRAINS: tuple[str, ...] = ("day", "week", "month", "quarter", "year")
_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def grain_next(start: Any, grain: str) -> Any:
    """The exclusive upper bound of the bucket a truncated ``start`` opens — the
    start of the NEXT period. Used to drill a bucket into ``[start, next)`` rows.
    ``start`` is Trunc's output (day 1 for month/quarter/year), so calendar
    month-advance keeps the day; day/week are fixed deltas."""
    from datetime import timedelta

    if grain == "day":
        return start + timedelta(days=1)
    if grain == "week":
        return start + timedelta(days=7)
    months = {"month": 1, "quarter": 3, "year": 12}[grain]
    m0 = start.month - 1 + months
    return start.replace(year=start.year + m0 // 12, month=m0 % 12 + 1)


def grain_label(start: Any, grain: str) -> str:
    """A readable axis label for a truncated period start (locale-free, so it's
    stable server-side regardless of platform ``strftime`` quirks)."""
    y, m, d = start.year, start.month, start.day
    if grain == "year":
        return str(y)
    if grain == "quarter":
        return f"Q{(m - 1) // 3 + 1} {y}"
    if grain == "month":
        return f"{_MONTH_ABBR[m]} {y}"
    if grain == "week":
        return f"Wk of {_MONTH_ABBR[m]} {d}, {y}"
    return f"{_MONTH_ABBR[m]} {d}, {y}"  # day


class Dataset:
    """Runtime wrapper around a registered ``DatasetDef``."""

    def __init__(self, dfn: DatasetDef) -> None:
        self.dfn = dfn
        self.key = dfn.key
        self._link_resolver_cache: Any = _UNSET

    # -- queryset / model ----------------------------------------------------

    def _queryset(self, request: HttpRequest | None = None) -> QuerySet:
        """Build the source queryset (lazy — no DB hit)."""
        fn = self.dfn.fn
        try:
            takes_arg = len(inspect.signature(fn).parameters) >= 1
        except (TypeError, ValueError):
            takes_arg = False
        return fn(request) if takes_arg else fn()

    @property
    def model(self) -> type[Model]:
        return self._queryset().model

    # -- columns (DB-free) ---------------------------------------------------

    def columns(self) -> list[tuple[str, str]]:
        """Resolve ``[(name, type)]``. No DB access."""
        model = self.model
        from apps.smallstack.api import _model_field_type

        if self.dfn.columns:
            resolved: list[tuple[str, str]] = []
            for col in self.dfn.columns:
                if isinstance(col, (tuple, list)):
                    resolved.append((col[0], col[1]))
                else:
                    resolved.append((col, _model_field_type(model, col)))
            return resolved
        return [(f.name, _model_field_type(model, f.name)) for f in model._meta.fields if not f.primary_key]

    def column_names(self) -> list[str]:
        return [name for name, _ in self.columns()]

    def fk_column_names(self) -> set[str]:
        """Names of columns the schema classifies as foreign keys."""
        return {name for name, typ in self.columns() if typ == "fk"}

    def filter_field_names(self) -> list[str]:
        if self.dfn.filterable is not None:
            return list(self.dfn.filterable)
        return self.column_names()

    def declared_measures(self) -> dict[str, dict]:
        """Declared ratio measures as ``{name: {num, denom, fmt}}`` ("" if none)."""
        out: dict[str, dict] = {}
        for entry in self.dfn.measures or []:
            name, num, denom = entry[0], entry[1], entry[2]
            fmt = entry[3] if len(entry) > 3 else "ratio"
            out[name] = {"num": num, "denom": denom, "fmt": fmt}
        return out

    def aggregate_expression(self, agg: str, measure: Optional[str]) -> Any:
        """The ORM aggregate for *agg* over *measure* — what :meth:`series`
        annotates with. A declared ratio measure brings its own aggregation
        (``sum(num) / sum(denom)``), so *agg* is ignored for it. For callers
        that group a :meth:`queryset` themselves; validate *measure* first."""
        declared = self.declared_measures()
        if measure and measure in declared:
            return _ratio_expr(declared[measure])
        return _agg_func(agg or "count", measure or None)

    def column_label(self, name: str) -> str:
        """A column's human label (the model field's ``verbose_name``)."""
        return _label_for(self.model, name)

    def column_labels(self) -> dict[str, str]:
        """``{column: label}`` for every column — cheap (no distinct-value
        probes, unlike :meth:`schema`), so it's safe per request."""
        try:
            return {name: self.column_label(name) for name, _typ in self.columns()}
        except Exception:  # noqa: BLE001 — labels are cosmetic
            logger.debug("Couldn't label the columns of dataset %s", self.key, exc_info=True)
            return {}

    def filter_column_types(self) -> dict[str, str]:
        """``{name: type}`` for every filterable name — the vocabulary a filter
        tree may reference. A filterable name that isn't a declared column is
        typed from the model (it filters but isn't displayed)."""
        from apps.smallstack.api import _model_field_type

        cols = dict(self.columns())
        out: dict[str, str] = {}
        for name in self.filter_field_names():
            out[name] = cols.get(name) or _model_field_type(self.model, name)
        return out

    def compile_tree(self, filter_tree: Any) -> Any:
        """Compile a stored filter tree against this dataset → ``Q`` or None.
        Raises ``FilterTreeError`` (a ValueError → HTTP 400) on any problem —
        a condition is never silently dropped (see filter_tree.py)."""
        types = self.filter_column_types()
        return compile_filter_tree(filter_tree, columns=types, filterable=set(types))

    def validate_filter_tree(self, filter_tree: Any) -> list[str]:
        """Every problem with *filter_tree* on this dataset (empty = valid)."""
        from .filter_tree import validate_filter_tree

        types = self.filter_column_types()
        problems = validate_filter_tree(filter_tree, columns=types, filterable=set(types))
        return problems or self._choice_problems(filter_tree)

    def _choice_problems(self, node: Any) -> list[str]:
        """A leaf comparing a choices column with a value it can never hold. It
        compiles, matches nothing and reads as a clean zero, so a metric on a
        misremembered status stays green for ever."""
        if isinstance(node, dict) and not node.get("field"):
            return [p for child in node.values() for p in self._choice_problems(child)]
        if isinstance(node, list):
            return [p for child in node for p in self._choice_problems(child)]
        if not isinstance(node, dict) or node.get("op") not in ("=", "!=", "in"):
            return []
        try:
            choices = getattr(self.model._meta.get_field(node["field"]), "choices", None)
        except Exception:  # noqa: BLE001 — a computed column has no model field
            return []
        if not choices:
            return []
        allowed = [str(key) for key, _label in choices]
        raw = node.get("value")
        values = raw if isinstance(raw, list) else [raw]
        wrong = [v for v in values if str(v) not in allowed]
        return [f"{node['field']}: {v!r} isn't one of its values ({', '.join(allowed)})" for v in wrong]

    # -- row links ("where can I view this object?") --------------------------

    def _link_resolver(self) -> Optional[Callable[[Any], Optional[str]]]:
        """The per-object URL resolver, or None when rows carry no link.

        Resolution order: the dataset's explicit ``link=`` (a callable, or a
        route name reversed with ``pk=``), else the model's CRUDView detail
        route (every explorer-registered model has one), else the model's
        ``get_absolute_url()``. ``link=False`` opts out. Computed once per
        Dataset instance; the only DB-free thing here is the lookup itself.
        """
        if self._link_resolver_cache is not _UNSET:
            cached: Optional[Callable[[Any], Optional[str]]] = self._link_resolver_cache
            return cached
        self._link_resolver_cache = self._build_link_resolver()
        return self._link_resolver_cache

    def _build_link_resolver(self) -> Optional[Callable[[Any], Optional[str]]]:
        from django.urls import NoReverseMatch, reverse

        link = self.dfn.link
        if link is False:
            return None
        if callable(link):
            return link
        if isinstance(link, str) and link:
            route = link

            def by_route(obj: Any) -> Optional[str]:
                try:
                    return reverse(route, kwargs={"pk": obj.pk})
                except NoReverseMatch:
                    return None

            return by_route

        model = self.model
        try:
            from apps.smallstack.crud import Action, CRUDView

            crud = CRUDView._registry.get(model)
        except Exception:  # noqa: BLE001 — datasets must work without the CRUD layer
            crud = None
        if crud is not None:
            # Same fallback {% crud_table %} documents: no DETAIL ⇒ link the
            # row to its edit page; neither ⇒ no link.
            suffix = "detail" if Action.DETAIL in crud.actions else "update" if Action.UPDATE in crud.actions else None
            if suffix is not None:
                route_name = f"{crud._get_url_base()}-{suffix}"

                def by_crud(obj: Any) -> Optional[str]:
                    try:
                        return crud._reverse(route_name, kwargs={"pk": obj.pk})
                    except NoReverseMatch:
                        return None

                return by_crud

        if callable(getattr(model, "get_absolute_url", None)):

            def by_absolute(obj: Any) -> Optional[str]:
                return obj.get_absolute_url() or None

            return by_absolute
        return None

    def has_links(self) -> bool:
        """True when ``rows()`` carries a ``url`` key. A dataset column that is
        itself named ``url`` keeps its meaning — links are then not added."""
        return LINK_KEY not in self.column_names() and self._link_resolver() is not None

    @property
    def has_detail(self) -> bool:
        """Deprecated: the name call_stats' original used. Use :meth:`has_links`."""
        warnings.warn("Dataset.has_detail is deprecated, use has_links() instead.", DeprecationWarning, stacklevel=2)
        return self.has_links()

    def link_for(self, obj: Any) -> Optional[str]:
        """The URL where *obj* (a row's model instance) can be viewed, or None.
        Never raises — a link that can't be built is simply absent."""
        resolver = self._link_resolver()
        if resolver is None or obj is None:
            return None
        try:
            return resolver(obj) or None
        except Exception:  # noqa: BLE001 — a bad link must not break the row
            logger.debug("Link resolver of dataset %s raised", self.key, exc_info=True)
            return None

    # -- schema (may hit DB via _build_filter_meta's distinct-value probe) ----

    def schema(self) -> dict:
        """Typed columns (dimension vs measure) + filter widget metadata."""
        from apps.smallstack.crud import _build_filter_meta

        from .capabilities import capabilities
        from .dateranges import RELATIVE_PERIODS

        model = self.model
        cols = self.columns()
        units = self.dfn.units or {}
        columns: list[dict[str, Any]] = [
            {
                "name": name,
                "label": _label_for(model, name),
                "type": typ,
                "role": "measure" if typ in _MEASURE_TYPES else "dimension",
                # Declared wins; else a guess from the name; else None.
                "unit": units.get(name) or _infer_unit(name),
            }
            for name, typ in cols
        ]
        # Declared ratio measures are computed, not real columns — surface them
        # so builders offer them like any measure (role=measure, computed=true).
        # A "percent" ratio is a percentage, so that's its unit by default.
        for mname, spec in self.declared_measures().items():
            columns.append(
                {
                    "name": mname,
                    "label": mname.replace("_", " ").capitalize(),
                    "type": spec["fmt"],
                    "role": "measure",
                    "computed": True,
                    "unit": units.get(mname) or ("percent" if spec["fmt"] == "percent" else None),
                }
            )
        date_types = {"date", "datetime"}
        col_types = dict(cols)
        filter_names = set(self.filter_field_names())
        filters = []
        for name, typ in cols:
            if name not in filter_names:
                continue
            # _build_filter_meta needs a MODEL field, so a computed (annotated)
            # column declared filterable produced no widget at all — a builder
            # UI could not offer the control even though the filter applies
            # (v0.21.11 fixed the applying half). Fall back to a synthesized
            # widget typed from the annotation.
            meta = _build_filter_meta(model, name) or self._computed_filter_meta(name)
            if meta:
                # Date/datetime columns also accept explicit half-open bounds
                # (<col>__gte / <col>__lt) — advertise so UIs can offer a range
                # picker alongside the preset dropdown.
                if col_types.get(name) in date_types:
                    meta["range"] = True
                    meta["periods"] = [{"key": k, "label": lbl} for k, lbl in RELATIVE_PERIODS]
                # The filter-tree operators this column accepts (a builder's
                # op dropdown) and its schema type (value coercion).
                meta["column_type"] = col_types.get(name, "string")
                meta["ops"] = ops_for_type(col_types.get(name, "string"))
                # The flat-key suffixes it accepts (<col>__gt=…, <col>__period=mtd).
                meta["lookups"] = list(_LOOKUPS_BY_TYPE.get(col_types.get(name, "string"), ()))
                filters.append(meta)
        out = {
            "key": self.key,
            "label": self.dfn.label,
            "description": self.dfn.description,
            "columns": columns,
            "filters": filters,
            "aggs": [a for a in _AGG_NAMES if a != "median" or median_supported(self._queryset().db)],
            # Rows carry a ``url`` key pointing at the object's page.
            "links": self.has_links(),
        }
        out["capabilities"] = sorted(capabilities(out))
        return out

    # -- computed-column filter widgets --------------------------------------

    #: Distinct-value ceiling for turning a computed column into a dropdown.
    #: Same number ``_build_filter_meta`` uses for model fields, deliberately —
    #: the two paths should feel identical to a builder UI.
    _COMPUTED_CHOICE_MAX = 30

    def _computed_filter_meta(self, name: str) -> dict | None:
        """Filter-widget metadata for a COMPUTED (annotated) column.

        Mirrors ``_build_filter_meta``'s conventions, including its
        distinct-value probe, so the widget and the comparison agree. That
        pairing is the whole point: in this framework a **choice widget means
        an exact match** and a text widget means ``icontains`` — and computed
        columns always compare exactly (see ``_filter_annotated_column``), so
        a dropdown is the only widget whose semantics we can honour.

        Returns ``None`` — i.e. advertise nothing, as before — when we cannot:

        * the name isn't an annotation (nothing to introspect);
        * the annotation is an **aggregate** (the distinct probe would mean a
          GROUP BY over the whole table, and the filter is a HAVING clause);
        * there are too many distinct values, which would need a text box
          promising substring matching that the exact comparison won't deliver.

        The filter itself still applies in every one of those cases; it just
        isn't offered as a control. Honest beats convenient — a widget that
        lies is worse than no widget.
        """
        from django.db import models as _m

        try:
            annotation = self._queryset().query.annotations.get(name)
        except Exception:  # noqa: BLE001 — a dataset that can't build is not our problem here
            logger.debug("Dataset %s couldn't build its queryset to read %s", self.key, name, exc_info=True)
            return None
        if annotation is None:
            return None

        meta: dict[str, Any] = {"name": name, "label": _label_for(self.model, name)}

        try:
            output_field = annotation.output_field
        except Exception:  # noqa: BLE001 — mixed-type expression
            output_field = None

        # Booleans and dates need no probe — their domain is known up front.
        if isinstance(output_field, _m.BooleanField):
            meta["type"] = "boolean"
            meta["choices"] = [("", "All"), ("true", "Yes"), ("false", "No")]
            return meta

        if isinstance(output_field, (_m.DateField, _m.DateTimeField)):
            meta["type"] = "choice"
            meta["is_date"] = True
            meta["choices"] = [
                ("", "All"),
                ("today", "Today"),
                ("yesterday", "Yesterday"),
                ("week", "Past 7 days"),
                ("month", "This month"),
                ("year", "This year"),
            ]
            return meta

        if getattr(annotation, "contains_aggregate", False):
            return None

        try:
            qs = self._queryset()
            if qs.values(name).distinct().count() > self._COMPUTED_CHOICE_MAX:
                return None
            values = qs.values_list(name, flat=True).distinct().order_by(name)[: self._COMPUTED_CHOICE_MAX]
            choices = [("", "All")] + [(str(v), str(v)) for v in values if v is not None]
        except Exception:  # noqa: BLE001 — un-probeable expression: offer nothing
            logger.debug("Couldn't probe the values of %s on dataset %s", name, self.key, exc_info=True)
            return None

        meta["type"] = "choice"
        meta["choices"] = choices
        return meta

    # -- shared filter application (one contract for rows/series/scalar) ------

    def queryset(
        self,
        request: HttpRequest | None = None,
        filters: Optional[dict] = None,
        *,
        filter_tree: Any = None,
    ) -> QuerySet:
        """Public seam: the dataset's queryset with the standard filter pipeline
        applied — and nothing else (no serialization, limit, ordering, expand).

        This is the supported way for a higher layer to *compose* on a dataset
        (its own aggregation, annotation, pagination) without touching internals.
        Same filter contract as :meth:`rows` (unknown keys ignored); per-user
        scoping via the dataset function's ``request`` arg happens inside::

            qs = get_dataset("open_tickets").queryset(request, {"status": "open"})
            # → a plain QuerySet you own from here

        Guaranteed: ``queryset(r, f).count() == len(rows(request=r, filters=f))``
        for the same filters (unlimited). ``filter_tree`` (a stored AND/OR
        tree, see filter_tree.py) is AND-ed on top and raises on any problem.
        """
        return self._filtered_qs(request, filters, filter_tree)

    def _filtered_qs(
        self,
        request: HttpRequest | None,
        filters: Optional[dict],
        filter_tree: Any = None,
    ) -> QuerySet:
        """Source queryset with *filters* applied via the CRUD list pipeline.

        The single filter-application path shared by ``rows``, ``series`` and
        ``scalar`` — so all three read paths honour the same filter contract
        (an active builder filter reduces the table, the chart *and* the KPI).
        Unknown filter keys are tolerated (ignored) exactly as the list view
        tolerates them.

        FILTER INVARIANT (stable across releases — see docs/skills/datasets.md):
        ``filters`` is a FLAT, string-keyed ``{name: scalar}`` mapping — the
        serializable query-param shape that stored slice descriptors, dashboard
        links, and agent calls depend on. Richer semantics arrive only as NEW
        param spellings (e.g. ``created_at__gte``), never as nested structures
        replacing existing keys.

        The nested AND/OR form is the separate ``filter_tree`` argument — the
        stored shape — compiled strictly (``compile_tree``) and AND-ed with the
        flat filters. Unlike an unknown flat key, a bad tree raises.

        Explicit lookups (``<col>__gte`` and the rest of ``_LOOKUPS_BY_TYPE``)
        are strict about their *value* the same way: blank means absent, but a
        value that won't parse raises ValueError (→ 400). Ignoring it would drop
        the narrowing and return more rows than the caller asked for.
        """
        from apps.smallstack.crud import _apply_list_filters as apply_filters

        qs = self._queryset(request)
        if not is_empty(filter_tree):
            tree_q = self.compile_tree(filter_tree)
            if tree_q is not None:
                qs = qs.filter(tree_q)
        if not filters:
            return qs

        # Pull out the explicit lookups and apply them directly — the CRUD
        # pipeline only knows bare-column presets and equality. An explicit
        # lookup on a column drops that column's bare preset (explicit wins).
        lookup_filters, flat_filters = self._split_range_filters(filters)
        types = self.filter_column_types()
        for key, raw in lookup_filters.items():
            if raw in (None, ""):
                continue
            qs = self._apply_lookup(qs, key, raw, types)

        pairs = "&".join(f"{k}={v}" for k, v in flat_filters.items() if v not in (None, ""))
        if pairs:
            filter_req = _fake_request(getattr(request, "user", None), pairs)
            qs = apply_filters(qs, filter_req, _ConfigAdapter(self))
        return qs

    def _split_range_filters(self, filters: dict) -> tuple[dict, dict]:
        """Separate explicit-lookup keys from the flat filters.

        A key qualifies when its column is filterable and its suffix is one the
        column's type takes (``_LOOKUPS_BY_TYPE``): ``__gte`` / ``__gt`` /
        ``__lte`` / ``__lt`` on dates and numbers, ``__period`` on dates,
        ``__ne`` / ``__icontains`` on text. Anything else stays a flat filter.
        A lookup on a column also suppresses that column's bare key.
        """
        types = self.filter_column_types()
        lookups, flat = {}, {}
        looked_up = set()
        for key, val in filters.items():
            base, sep, lookup = key.partition("__")
            if sep and lookup in _LOOKUPS_BY_TYPE.get(types.get(base, ""), ()):
                lookups[key] = val
                looked_up.add(base)
            else:
                flat[key] = val
        for col in looked_up:
            flat.pop(col, None)  # an explicit lookup wins over the bare key
        return lookups, flat

    def filter_problems(self, filters: Optional[dict]) -> list[str]:
        """Every explicit lookup in *filters* whose value won't parse (empty =
        all apply). DB-free: what :meth:`queryset` would raise, said up front,
        for a page that shows the problem instead of an error."""
        lookups, _flat = self._split_range_filters(filters or {})
        types = self.filter_column_types()
        empty = self.model._default_manager.none()
        problems = []
        for key, raw in lookups.items():
            if raw in (None, ""):
                continue
            try:
                self._apply_lookup(empty, key, raw, types)
            except ValueError as exc:
                problems.append(str(exc))
        return problems

    @staticmethod
    def _apply_lookup(qs: QuerySet, key: str, raw: Any, types: dict[str, str]) -> QuerySet:
        """Apply one explicit lookup; ValueError when *raw* won't parse."""
        base, _, lookup = key.partition("__")
        typ = types.get(base, "")
        if lookup == "ne":  # "is not": rows without a value are kept
            return qs.exclude(**{base: raw})
        if lookup == "icontains":
            return qs.filter(**{key: raw})
        if lookup == "period":
            from .dateranges import relative_dates, relative_range

            bounds = relative_dates(str(raw)) if typ == "date" else relative_range(str(raw))
            if bounds is None:
                raise ValueError(f"{key}: unknown period {raw!r}")
            return qs.filter(**{f"{base}__gte": bounds[0], f"{base}__lt": bounds[1]})
        if typ in _DATE_TYPES:
            parsed = _parse_date_bound(raw)
            kind = "an ISO date or datetime"
        else:
            parsed = _parse_number(raw, whole=typ == "integer")
            kind = "a whole number" if typ == "integer" else "a number"
        if parsed is None:
            raise ValueError(f"{key}: {raw!r} isn't {kind}")
        return qs.filter(**{key: parsed})

    # -- rows (sub-filtering reduces the row count) --------------------------

    def _scoped_qs(
        self,
        request: HttpRequest | None,
        filters: Optional[dict],
        dimension: Optional[dict] = None,
        bucket: Optional[str] = None,
        filter_tree: Any = None,
    ) -> QuerySet:
        """Filtered queryset, optionally narrowed to one bucket of *dimension*
        (the drilldown). Re-applies the *same* ``_bucket_cond`` the bucketed
        series used, so ``count(bucket=K) == series bucket K``'s value by
        construction. Unknown field/bucket raise ValueError (→ 400)."""
        qs = self._filtered_qs(request, filters, filter_tree)
        if dimension and bucket is not None:
            from .buckets import _bucket_cond, _dimension_values, bucket_by_key, resolve_buckets

            field = dimension.get("field")
            if field not in set(self.column_names()):
                raise ValueError(f"unknown dimension field {field!r}")
            buckets = resolve_buckets(self, dimension, request)
            b = bucket_by_key(buckets, bucket)
            if b is None:
                raise ValueError(f"unknown bucket {bucket!r}")
            qs = qs.filter(_bucket_cond(field, b, _dimension_values(buckets)))
        return qs

    def count(
        self,
        request: HttpRequest | None = None,
        filters: Optional[dict] = None,
        *,
        dimension: Optional[dict] = None,
        bucket: Optional[str] = None,
        filter_tree: Any = None,
    ) -> int:
        """Total rows matching *filters* (unpaged) — the companion to a paged
        ``rows()`` call so a table UI can show "showing 1–50 of N". Pass
        ``dimension``+``bucket`` for a bucket drilldown's total."""
        return self._scoped_qs(request, filters, dimension, bucket, filter_tree).count()

    def rows(
        self,
        *,
        filters: Optional[dict] = None,
        ordering: str = "",
        limit: Optional[int] = 50,
        offset: int = 0,
        expand: Optional[list[str]] = None,
        dimension: Optional[dict] = None,
        bucket: Optional[str] = None,
        request: HttpRequest | None = None,
        filter_tree: Any = None,
    ) -> list[dict]:
        """Filtered rows. ``limit=None`` returns the whole filtered set (used by
        CSV export); ``offset`` pages after ordering. Invalid values coerce to
        the default (matching the module's absent-not-error stance).

        ``dimension``+``bucket`` narrows to one bucket of a bucketed series (the
        drilldown) — the rows behind a clicked chart segment, reconciling with
        that bucket's count by construction."""
        from apps.smallstack.api import serialize
        from apps.smallstack.crud import (
            _apply_ordering_fields as apply_ordering,
        )

        qs = self._scoped_qs(request, filters, dimension, bucket, filter_tree)

        if ordering:
            qs = apply_ordering(qs, ordering, set(self.column_names()))

        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0

        if limit is None:
            page = slice(offset, None)  # whole set (offset→end)
        else:
            try:
                limit = max(1, min(int(limit or 50), _ROWS_LIMIT_MAX))
            except (TypeError, ValueError):
                limit = 50
            page = slice(offset, offset + limit)

        field_names = self.column_names()

        # A computed/annotated dataset (``.values(...).annotate(...)``) yields
        # plain dicts, not model instances — they have no ``.pk`` for
        # ``serialize`` and are already the shape a table wants. Return them
        # projected onto the declared columns (plus any annotations they carry).
        if getattr(qs.query, "values_select", None):
            return [self._project_dict_row(row, field_names) for row in qs[page]]

        # Only expand FK columns the schema actually knows about, so a bad
        # ``expand`` param can never raise inside ``serialize``.
        expand_fields = self.fk_column_names() & set(expand or [])
        with_links = self.has_links()
        out: list[dict] = []
        for obj in qs[page]:
            row = serialize(obj, field_names, [], expand_fields)
            if with_links:
                row[LINK_KEY] = self.link_for(obj)
            out.append(row)
        return out

    @staticmethod
    def _project_dict_row(row: dict, field_names: list[str]) -> dict:
        """Shape a values-queryset dict into a stable row.

        Declared columns come first (missing keys → ``None``); any extra
        annotation keys the queryset carries are appended so callers still see
        aggregates like ``item_count`` even when they weren't declared columns.
        """
        out = {name: row.get(name) for name in field_names}
        for key, val in row.items():
            if key not in out:
                out[key] = val
        return out

    # -- series (group-by rollup → [{label, value}] for bar/pie) -------------

    def series(
        self,
        dimension: Any = None,
        *,
        measure: Optional[str] = None,
        agg: str = "count",
        grain: Optional[str] = None,
        sort: Optional[dict] = None,
        limit: int = 50,
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
        filter_tree: Any = None,
    ) -> list[dict]:
        """Grouped rollup → ``[{label, value}]`` for bar/pie.

        ``filters`` are applied through the same path as :meth:`rows` (one
        filter contract across all three read paths) so the chart reflects the
        builder's active filters.

        ``dimension`` may be:

        - a **string** column name → group by its raw values (with ``measure``/
          ``agg``, or a declared ratio measure). When it names a date/datetime
          column and ``grain`` (day/week/month/quarter/year) is given, group by
          the calendar-truncated period instead — a trend series of the most
          recent ``limit`` periods in chronological order, each row carrying
          ``lo``/``hi`` ISO bounds so a bar drills into exactly that period's
          ``[lo, hi)`` rows (the call_stats grammar);
        - a **dict** ``{"field": …, "buckets": […]}`` or ``{"field": …, "auto":
          …}`` → **bucketed** grouping (numeric bands / categorical / auto
          top-N + ``other``), returning ``[{key, label, value, lo, hi}]`` where
          ``value`` is the bucket's row count (count-only — ``measure``/``agg``
          don't apply here);
        - ``None`` → a single ungrouped aggregate (the KPI/scalar path).

        ``sort`` (``{"by": "category"|"value", "dir": "asc"|"desc"}``) orders a
        grouped series. The default, category ascending, is the dimension's (or
        the period's) order. ``by: "value"`` ranks by the aggregate, and because
        the database applies it before ``limit``, ``value``/``desc`` is a top-N.
        A time grain keeps its window: the most recent ``limit`` periods, then
        sorted for display. A group with no value sorts last either way.
        """
        if isinstance(dimension, dict):
            return self._bucketed_series(dimension, filters=filters, request=request, filter_tree=filter_tree)

        if agg not in _AGG_NAMES:
            agg = "count"
        by, descending = _sort_spec(sort)

        # A declared ratio measure (sum(num)/sum(denom)) is computed, not a real
        # column — it defines its own aggregation, so ``agg`` doesn't apply and
        # the empty-denominator group yields None (never 0, never averaged).
        declared = self.declared_measures()
        is_ratio = bool(measure) and measure in declared

        # Validate dimension/measure against the declared columns *before*
        # touching the ORM, so a bad param yields a clean ValueError (mapped to
        # HTTP 400 at the view boundary) rather than a raw FieldError / 500.
        # Mirrors how ``rows()`` already tolerates unknown ordering/filter keys.
        valid = set(self.column_names())
        if dimension is not None and dimension not in valid:
            raise ValueError(f"unknown dimension {dimension!r}; valid: {sorted(valid)}")
        if measure and not is_ratio and measure not in valid:
            raise ValueError(f"unknown measure {measure!r}; valid: {sorted(valid | set(declared))}")

        value_expr = self.aggregate_expression(agg, measure)

        qs = self._filtered_qs(request, filters, filter_tree)
        self._check_median(agg, measure, is_ratio, qs)

        # KPI / scalar path — no GROUP BY, single aggregate over the filtered set.
        if dimension is None:
            value = qs.aggregate(_value=value_expr)["_value"]
            if value is None and not is_ratio and agg in _ZERO_WHEN_EMPTY:
                value = 0  # count/sum of nothing is 0; avg/min/max/ratio of nothing has no value
            return [{"label": (measure if is_ratio else agg), "value": _round_value(value)}]

        try:
            limit = max(1, min(int(limit or 50), _SERIES_LIMIT_MAX))
        except (TypeError, ValueError):
            limit = 50

        # A date/datetime dimension with a `grain` → a time-truncated trend: the
        # most recent `limit` periods (a long daily span shows recent history,
        # not the oldest slice), returned chronologically.
        if grain and dict(self.columns()).get(dimension) in ("date", "datetime"):
            trunc = _grain_truncs().get(grain)
            if trunc is None:
                raise ValueError(f"unknown grain {grain!r}; valid: {list(GRAINS)}")
            periods = (
                qs.annotate(_period=trunc(dimension))
                .values("_period")
                .annotate(_value=value_expr)
                .order_by("-_period")[:limit]
            )
            trend = [
                {
                    "label": grain_label(row["_period"], grain),
                    "value": _round_value(row["_value"]),
                    "lo": row["_period"].isoformat(),
                    "hi": grain_next(row["_period"], grain).isoformat(),
                }
                for row in periods
                if row["_period"] is not None
            ]
            if by == "value":
                valued = sorted((r for r in trend if r["value"] is not None), key=lambda r: r["value"])
                trend = (valued[::-1] if descending else valued) + [r for r in trend if r["value"] is None]
            else:
                trend.sort(key=lambda r: r["lo"], reverse=descending)  # ISO starts sort chronologically
            return trend

        from django.db.models import F

        annotated = qs.values(dimension).annotate(_value=value_expr)
        if by == "value":
            ranked = F("_value").desc(nulls_last=True) if descending else F("_value").asc(nulls_last=True)
            annotated = annotated.order_by(ranked, dimension)  # ties read in the dimension's order
        else:
            annotated = annotated.order_by(F(dimension).desc() if descending else F(dimension).asc())

        rows = list(annotated[:limit])

        # When the dimension is an FK, its group-by values are bare pks — resolve
        # them to the related object's ``str()`` so charts read "Electrical",
        # not "2". Single extra query (pk→name map), not N.
        label_map = self.value_labels(dimension, rows)

        out = []
        for row in rows:
            raw = row.get(dimension)
            label = label_map.get(raw) if label_map else None
            out.append(
                {
                    "label": label if label is not None else _series_label(raw),
                    "value": _round_value(row["_value"]),
                }
            )
        return out

    @staticmethod
    def _check_median(agg: str, measure: Optional[str], is_ratio: bool, qs: QuerySet) -> None:
        """A median needs a plain numeric column and a database that has one."""
        if agg != "median" or is_ratio:
            return
        if not measure:
            raise ValueError("median needs a measure: the median of what?")
        if not median_supported(qs.db):
            raise ValueError("median isn't available on this database (PostgreSQL, SQLite and Oracle have it)")

    # -- cells (two dimensions → a complete x × y grid) -----------------------

    def cells(
        self,
        dimension: str,
        dimension2: str,
        *,
        measure: Optional[str] = None,
        agg: str = "count",
        axis_limit: int = _CELLS_AXIS_MAX,
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
        filter_tree: Any = None,
    ) -> list[dict]:
        """Two-dimensional rollup → ``[{x, x_label, y, y_label, value}]`` for a
        heatmap or punch card: :meth:`series` grouped by *dimension* (x) and
        *dimension2* (y) at once.

        - **The grid is complete:** every x × every y that occurs in the
          filtered rows, row-major by y then x, so a chart can index marks by
          position. A combination with no rows carries the empty value: 0 for
          count/distinct/sum, None for the rest (an average of nothing isn't 0).
        - **Raw values ride with labels** (``x`` and ``x_label``), so a drill-down
          filters on the stored value (an FK's pk) and shows the name.
        - **Axes are capped, loudly:** more than ``axis_limit`` distinct values on
          either axis raises ValueError naming the field and its count, rather
          than leaving part of the grid out.

        Filters ride the same path as :meth:`rows` and :meth:`series`.
        """
        if agg not in _AGG_NAMES:
            agg = "count"
        declared = self.declared_measures()
        is_ratio = bool(measure) and measure in declared
        valid = set(self.column_names())
        for name, which in ((dimension, "dimension"), (dimension2, "dimension2")):
            if name not in valid:
                raise ValueError(f"unknown {which} {name!r}; valid: {sorted(valid)}")
        if dimension == dimension2:
            raise ValueError("dimension and dimension2 must be different columns")
        if measure and not is_ratio and measure not in valid:
            raise ValueError(f"unknown measure {measure!r}; valid: {sorted(valid | set(declared))}")

        qs = self._filtered_qs(request, filters, filter_tree)
        self._check_median(agg, measure, is_ratio, qs)
        grouped = list(
            qs.values(dimension, dimension2).annotate(_value=self.aggregate_expression(agg, measure)).order_by()
        )

        def axis(field: str) -> list:
            seen = {row[field] for row in grouped}
            return sorted(v for v in seen if v is not None) + ([None] if None in seen else [])

        xs, ys = axis(dimension), axis(dimension2)
        for name, values in ((dimension, xs), (dimension2, ys)):
            if len(values) > axis_limit:
                raise ValueError(
                    f"{name!r} has {len(values)} distinct values; a cell chart takes at most {axis_limit} "
                    "on an axis. Group by a column with fewer values, or filter first."
                )

        x_labels, y_labels = self.value_labels(dimension, grouped), self.value_labels(dimension2, grouped)
        empty: Any = 0 if agg in _ZERO_WHEN_EMPTY and not is_ratio else None
        found = {(row[dimension], row[dimension2]): row["_value"] for row in grouped}
        return [
            {
                "x": x,
                "x_label": x_labels[x] if x in x_labels else _series_label(x),
                "y": y,
                "y_label": y_labels[y] if y in y_labels else _series_label(y),
                "value": _round_value(found[(x, y)]) if (x, y) in found else empty,
            }
            for y in ys
            for x in xs
        ]

    # -- bucketed series (numeric bands / categorical / auto top-N) -----------

    def _bucketed_series(
        self,
        dimension: dict,
        *,
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
        filter_tree: Any = None,
    ) -> list[dict]:
        """Count-only bucketed rollup → ``[{key, label, value, lo, hi}]``.

        One ``.aggregate()`` of per-bucket filtered ``Count``s (a single query).
        ``auto`` dimensions derive their buckets from the *unnarrowed* scope so
        keys stay stable across filters (a filtered series returns the same
        buckets, zero-counted where empty). With an ``other`` bucket present the
        counts sum to the filtered total — no silently dropped rows.
        """
        from django.db.models import Count

        from .buckets import _bucket_cond, _dimension_values, resolve_buckets

        field = dimension.get("field")
        if field not in set(self.column_names()):
            raise ValueError(f"unknown dimension field {field!r}; valid: {sorted(self.column_names())}")

        buckets = resolve_buckets(self, dimension, request)
        if not buckets:
            return []
        dvals = _dimension_values(buckets)

        qs = self._filtered_qs(request, filters, filter_tree)
        anns = {b["key"]: Count("id", filter=_bucket_cond(field, b, dvals)) for b in buckets}
        row = qs.aggregate(**anns)
        return [
            {
                "key": b["key"],
                "label": b["label"],
                "value": row[b["key"]] or 0,
                "lo": b.get("lo"),
                "hi": b.get("hi"),
            }
            for b in buckets
        ]

    # -- scalar (ungrouped aggregate → a single number for a KPI tile) --------

    def scalar(
        self,
        *,
        measure: Optional[str] = None,
        agg: str = "count",
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
        filter_tree: Any = None,
    ) -> Any:
        """One number for a KPI tile — an ungrouped ``qs.aggregate()``.

        ``agg="count"`` (or no ``measure``) counts rows; otherwise the measure
        column is aggregated. ``filters`` are applied through the same path as
        :meth:`rows`, so the KPI reflects the builder's active filters. Rolls up
        in the database, not in Python — the first-class path the "KPI tile"
        affordance needs (no GROUP BY).
        """
        return self.series(None, measure=measure, agg=agg, filters=filters, request=request, filter_tree=filter_tree)[
            0
        ]["value"]

    def _fk_label_map(self, dimension: str, rows: list[dict]) -> dict:
        """Deprecated: the name call_stats' original used. Use :meth:`value_labels`."""
        warnings.warn(
            "Dataset._fk_label_map is deprecated, use value_labels() instead.", DeprecationWarning, stacklevel=2
        )
        return self.value_labels(dimension, rows)

    def value_labels(self, dimension: str, rows: list[dict]) -> dict:
        """Map FK pks in *rows* to the related object's ``str()``, or a choices
        column's stored values to their labels ("high" → "High"). ``{}`` for any
        other column. For labelling a grouped :meth:`queryset`."""
        if dimension not in self.fk_column_names():
            try:
                choices = getattr(self.model._meta.get_field(dimension), "flatchoices", None)
            except Exception:  # an annotated or computed column: no model field
                return {}
            return {key: str(label) for key, label in choices} if choices else {}
        try:
            field = self.model._meta.get_field(dimension)
            related = field.related_model
        except Exception:
            return {}
        if related is None:
            return {}
        pks = [r.get(dimension) for r in rows if r.get(dimension) is not None]
        if not pks:
            return {}
        # ``_default_manager`` (not ``objects``) so this works for related models
        # that rename their manager, and is what django-stubs types on a dynamic
        # ``type[Model]``.
        return {obj.pk: str(obj) for obj in related._default_manager.filter(pk__in=pks)}


class _ConfigAdapter:
    """Presents the ``crud_config`` interface the pipeline helpers expect."""

    def __init__(self, ds: Dataset) -> None:
        self._ds = ds
        self.model = ds.model
        self.ordering_fields = ds.column_names()
        self.api_aggregate_fields = [name for name, typ in ds.columns() if typ in _MEASURE_TYPES]

    def _resolve_filter_fields(self) -> list[str]:
        return self._ds.filter_field_names()

    def _resolve_search_fields(self) -> list[str]:
        return []

    def _get_list_fields(self) -> list[str]:
        return self._ds.column_names()


# ---------------------------------------------------------------------------
# Public accessors (the builder / REST / MCP entry points)
# ---------------------------------------------------------------------------


def get_dataset(key: str) -> Optional[Dataset]:
    dfn = get_def(key)
    return Dataset(dfn) if dfn is not None else None


def list_datasets(*, api_only: bool = False) -> list[dict]:
    """The picker list — lightweight metadata only (no DB, no schema probe)."""
    return [
        {"key": d.key, "label": d.label, "description": d.description}
        for d in all_defs()
        if not api_only or d.enable_api
    ]
