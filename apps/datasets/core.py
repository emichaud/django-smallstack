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

import inspect
from typing import Any, Callable, Optional

from django.db.models import Model, QuerySet
from django.http import HttpRequest, QueryDict

from .registry import DatasetDef, all_defs, get_def

# Types the framework classifies as numeric → chartable "measures".
_MEASURE_TYPES = {"integer", "float", "decimal"}
_SERIES_LIMIT_MAX = 500
_ROWS_LIMIT_MAX = 500
_AGG_NAMES = ("count", "sum", "avg", "min", "max")

#: The row key that carries the "view this object" URL (see Dataset.link_for).
LINK_KEY = "url"

_UNSET: Any = object()


def _agg_func(agg: str, measure: Optional[str]) -> Any:
    """Return the aggregate expression for ``agg`` over ``measure``.

    ``count`` (or a missing measure) counts rows; the others aggregate the
    measure column. ``agg`` is assumed validated by the caller.
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    if agg == "count" or not measure:
        return Count("id")
    return {"sum": Sum, "avg": Avg, "min": Min, "max": Max}[agg](measure)


def _round_value(val: Any) -> Any:
    return round(val, 2) if isinstance(val, float) else val


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
    """Parse an ISO date or datetime string for a ``__gte``/``__lt`` bound.
    Returns None on anything unparseable (garbage is ignored, not an error)."""
    from datetime import date, datetime

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


def _fake_request(user: Any = None, query: str = "") -> HttpRequest:
    """Minimal request so the pipeline helpers can read ``.user`` / ``.GET``."""
    req = HttpRequest()
    req.method = "GET"
    req.user = user
    req.GET = QueryDict(query, mutable=False)
    req.META = {}
    return req


def _label_for(model: type[Model], name: str) -> str:
    try:
        # get_field may return a reverse relation (ForeignObjectRel) with no
        # verbose_name — getattr falls through to the humanized name for those.
        field = model._meta.get_field(name)
        return str(getattr(field, "verbose_name", name)).capitalize()
    except Exception:
        return name.replace("_", " ").capitalize()


def _series_label(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


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

    def link_for(self, obj: Any) -> Optional[str]:
        """The URL where *obj* (a row's model instance) can be viewed, or None.
        Never raises — a link that can't be built is simply absent."""
        resolver = self._link_resolver()
        if resolver is None or obj is None:
            return None
        try:
            return resolver(obj) or None
        except Exception:  # noqa: BLE001 — a bad link must not break the row
            return None

    # -- schema (may hit DB via _build_filter_meta's distinct-value probe) ----

    def schema(self) -> dict:
        """Typed columns (dimension vs measure) + filter widget metadata."""
        from apps.smallstack.crud import _build_filter_meta

        model = self.model
        cols = self.columns()
        columns: list[dict[str, Any]] = [
            {
                "name": name,
                "label": _label_for(model, name),
                "type": typ,
                "role": "measure" if typ in _MEASURE_TYPES else "dimension",
            }
            for name, typ in cols
        ]
        # Declared ratio measures are computed, not real columns — surface them
        # so builders offer them like any measure (role=measure, computed=true).
        for mname, spec in self.declared_measures().items():
            columns.append(
                {
                    "name": mname,
                    "label": mname.replace("_", " ").capitalize(),
                    "type": spec["fmt"],
                    "role": "measure",
                    "computed": True,
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
                filters.append(meta)
        return {
            "key": self.key,
            "label": self.dfn.label,
            "description": self.dfn.description,
            "columns": columns,
            "filters": filters,
            # Rows carry a ``url`` key pointing at the object's page.
            "links": self.has_links(),
        }

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
            return None

        meta["type"] = "choice"
        meta["choices"] = choices
        return meta

    # -- shared filter application (one contract for rows/series/scalar) ------

    def queryset(
        self,
        request: HttpRequest | None = None,
        filters: Optional[dict] = None,
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
        for the same filters (unlimited).
        """
        return self._filtered_qs(request, filters)

    def _filtered_qs(
        self,
        request: HttpRequest | None,
        filters: Optional[dict],
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
        """
        from apps.smallstack.crud import _apply_list_filters as apply_filters

        qs = self._queryset(request)
        if not filters:
            return qs

        # Pull out explicit half-open date bounds (<col>__gte / <col>__lt) and
        # apply them directly — the CRUD pipeline only knows bare-column presets.
        # An explicit bound on a column drops that column's preset (explicit wins).
        range_filters, flat_filters = self._split_range_filters(filters)
        for key, raw in range_filters.items():
            parsed = _parse_date_bound(raw)
            if parsed is not None:  # garbage ignored (absent-not-error)
                qs = qs.filter(**{key: parsed})

        pairs = "&".join(f"{k}={v}" for k, v in flat_filters.items() if v not in (None, ""))
        if pairs:
            filter_req = _fake_request(getattr(request, "user", None), pairs)
            qs = apply_filters(qs, filter_req, _ConfigAdapter(self))
        return qs

    def _split_range_filters(self, filters: dict) -> tuple[dict, dict]:
        """Separate ``<datecol>__gte`` / ``__lt`` keys from the flat filters.

        A range on a column also suppresses that column's bare preset (so an
        explicit bound wins if both are sent). Only date/datetime columns in the
        filterable set qualify; anything else stays a flat filter.
        """
        date_cols = {
            name
            for name, typ in self.columns()
            if typ in ("date", "datetime") and name in set(self.filter_field_names())
        }
        range_filters, flat = {}, {}
        ranged_cols = set()
        for key, val in filters.items():
            base, sep, lookup = key.partition("__")
            if sep and lookup in ("gte", "lt") and base in date_cols:
                range_filters[key] = val
                ranged_cols.add(base)
            else:
                flat[key] = val
        for col in ranged_cols:
            flat.pop(col, None)  # explicit bounds win over the preset
        return range_filters, flat

    # -- rows (sub-filtering reduces the row count) --------------------------

    def _scoped_qs(
        self,
        request: HttpRequest | None,
        filters: Optional[dict],
        dimension: Optional[dict] = None,
        bucket: Optional[str] = None,
    ) -> QuerySet:
        """Filtered queryset, optionally narrowed to one bucket of *dimension*
        (the drilldown). Re-applies the *same* ``_bucket_cond`` the bucketed
        series used, so ``count(bucket=K) == series bucket K``'s value by
        construction. Unknown field/bucket raise ValueError (→ 400)."""
        qs = self._filtered_qs(request, filters)
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
    ) -> int:
        """Total rows matching *filters* (unpaged) — the companion to a paged
        ``rows()`` call so a table UI can show "showing 1–50 of N". Pass
        ``dimension``+``bucket`` for a bucket drilldown's total."""
        return self._scoped_qs(request, filters, dimension, bucket).count()

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

        qs = self._scoped_qs(request, filters, dimension, bucket)

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
        limit: int = 50,
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
    ) -> list[dict]:
        """Grouped rollup → ``[{label, value}]`` for bar/pie.

        ``filters`` are applied through the same path as :meth:`rows` (one
        filter contract across all three read paths) so the chart reflects the
        builder's active filters.

        ``dimension`` may be:

        - a **string** column name → group by its raw values (with ``measure``/
          ``agg``, or a declared ratio measure);
        - a **dict** ``{"field": …, "buckets": […]}`` or ``{"field": …, "auto":
          …}`` → **bucketed** grouping (numeric bands / categorical / auto
          top-N + ``other``), returning ``[{key, label, value, lo, hi}]`` where
          ``value`` is the bucket's row count (count-only — ``measure``/``agg``
          don't apply here);
        - ``None`` → a single ungrouped aggregate (the KPI/scalar path).
        """
        if isinstance(dimension, dict):
            return self._bucketed_series(dimension, filters=filters, request=request)

        if agg not in _AGG_NAMES:
            agg = "count"

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

        value_expr = _ratio_expr(declared[measure]) if is_ratio and measure is not None else _agg_func(agg, measure)

        qs = self._filtered_qs(request, filters)

        # KPI / scalar path — no GROUP BY, single aggregate over the filtered set.
        if dimension is None:
            value = qs.aggregate(_value=value_expr)["_value"]
            if value is None and not is_ratio:
                value = 0  # count/sum of nothing is 0; an empty ratio stays None
            return [{"label": (measure if is_ratio else agg), "value": _round_value(value)}]

        annotated = qs.values(dimension).annotate(_value=value_expr)
        annotated = annotated.order_by(dimension)

        try:
            limit = max(1, min(int(limit or 50), _SERIES_LIMIT_MAX))
        except (TypeError, ValueError):
            limit = 50

        rows = list(annotated[:limit])

        # When the dimension is an FK, its group-by values are bare pks — resolve
        # them to the related object's ``str()`` so charts read "Electrical",
        # not "2". Single extra query (pk→name map), not N.
        label_map = self._fk_label_map(dimension, rows)

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

    # -- bucketed series (numeric bands / categorical / auto top-N) -----------

    def _bucketed_series(
        self,
        dimension: dict,
        *,
        filters: Optional[dict] = None,
        request: HttpRequest | None = None,
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

        qs = self._filtered_qs(request, filters)
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
    ) -> Any:
        """One number for a KPI tile — an ungrouped ``qs.aggregate()``.

        ``agg="count"`` (or no ``measure``) counts rows; otherwise the measure
        column is aggregated. ``filters`` are applied through the same path as
        :meth:`rows`, so the KPI reflects the builder's active filters. Rolls up
        in the database, not in Python — the first-class path the "KPI tile"
        affordance needs (no GROUP BY).
        """
        return self.series(None, measure=measure, agg=agg, filters=filters, request=request)[0]["value"]

    def _fk_label_map(self, dimension: str, rows: list[dict]) -> dict:
        """Map FK pks in *rows* to the related object's ``str()``. ``{}`` if not an FK."""
        if dimension not in self.fk_column_names():
            return {}
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
