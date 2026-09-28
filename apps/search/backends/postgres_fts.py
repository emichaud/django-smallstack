"""PostgresFTSBackend — full-text search on PostgreSQL via a denormalized
``tsvector`` column plus a GIN index.

Mirrors the SQLiteFTSBackend's self-provisioning design: the backend owns
its index structure and creates it at runtime in ``ensure_index`` (hooked
to ``post_migrate``), rather than relying on per-model Django migrations.
This keeps the bundled SQLite-default models migration-clean — a
``SearchVectorField`` on a model would emit a ``tsvector`` column type that
SQLite can't build, and would make ``makemigrations`` drift against the
runtime-managed column — while still giving every indexed model (bundled
*and* downstream) a working Postgres index with zero extra steps.

Storage: one ``search_vector tsvector`` column added to each indexed
model's own table, kept current by the signal handlers in
``apps.search.signals`` (which call ``index_object``). Reads and writes use
raw SQL parameterized on Python-resolved field values — the same strategy
as the SQLite backend — so ``__`` field paths and unmapped columns work
uniformly, and the model never needs to declare the column.

Ranking uses ``ts_rank`` over the weighted vector (A > B > C > D from
``search_weight``). The text config defaults to ``english`` (stemming +
stopwords).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from django.db import connection

from .base import IndexedView, SearchHit
from .fallback import _make_hit, _resolve_field

logger = logging.getLogger("smallstack.search")

# search_weight int → Postgres tsvector weight label. 3 = highest (A).
_WEIGHT_LABELS = {3: "A", 2: "B", 1: "C", 0: "D"}

# to_postgres() search_type → the tsquery constructor that parses it.
_TSQUERY_FUNCS = {
    "plain": "plainto_tsquery",
    "phrase": "phraseto_tsquery",
    "raw": "to_tsquery",
}


class PostgresFTSBackend:
    name = "postgresql-fts"

    # ---- index lifecycle -------------------------------------------------

    def ensure_index(self, view: IndexedView) -> bool:
        """Add the ``search_vector`` column + GIN index if absent.

        Idempotent, and — once provisioned — issues **no DDL at all**: both
        the column and the index are existence-checked first, so it is safe
        to run on every ``post_migrate`` *and* from inside an open
        transaction that holds deferred constraint events. Self-provisioning here — rather than via a model
        field + migration — is what lets the bundled SQLite-default models
        opt into Postgres FTS without shipping a ``tsvector`` column that
        SQLite can't create.

        The GIN index is built with ``CREATE INDEX CONCURRENTLY`` so it never
        takes a write lock on a large, live table — the plain form can block
        every writer for the duration and time out silently on a big table.
        ``CONCURRENTLY`` can't run inside a transaction block, so it's only
        used when the connection is in autocommit (the normal ``post_migrate``
        state); inside an atomic block it falls back to the plain locking form,
        which is fine for the empty/small tables a fresh migrate sees.
        Failures are surfaced (return ``False`` → the doctor reports MISSING),
        not just logged and forgotten.
        """
        table = view.model._meta.db_table
        index = _gin_index_name(view)

        # 1. Column add — skipped entirely when already present. The guard is
        #    not just an optimisation: the no-op ALTER still takes an
        #    AccessExclusiveLock, and Postgres refuses it outright while the
        #    transaction holds pending deferred-constraint trigger events.
        if not _column_exists(table, "search_vector"):
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS search_vector tsvector'
                    )
            except Exception:
                logger.exception("PG-FTS add-column failed for %s", view.model_label)
                return False

        # 2. GIN index — skip if already present, else create (concurrently
        #    when we can).
        if _index_exists(index):
            return True
        concurrently = "" if connection.in_atomic_block else "CONCURRENTLY "
        sql = (
            f'CREATE INDEX {concurrently}IF NOT EXISTS "{index}" '
            f'ON "{table}" USING GIN (search_vector)'
        )
        try:
            with connection.cursor() as cur:
                cur.execute(sql)
        except Exception:
            logger.exception(
                "PG-FTS GIN index create failed for %s (index=%s)", view.model_label, index
            )
            return False
        return True

    def index_object(self, view: IndexedView, obj: Any) -> None:
        """Recompute the row's ``search_vector`` from its search fields.

        Field text is resolved in Python (so ``__`` paths work) and passed
        as bound parameters; the weight labels come from a fixed map and are
        inlined into the SQL (no user input reaches the statement text).
        """
        if not view.fields:
            return
        table = view.model._meta.db_table
        pk_col = view.model._meta.pk.column

        parts = []
        params: list[Any] = []
        for field_name in view.fields:
            label = _WEIGHT_LABELS.get(_clamp_weight(view.weights.get(field_name, 1)), "C")
            parts.append(f"setweight(to_tsvector('english', %s), '{label}')")
            params.append(str(_resolve_field(obj, field_name) or ""))
        set_expr = " || ".join(parts)
        params.append(obj.pk)

        sql = f'UPDATE "{table}" SET search_vector = {set_expr} WHERE "{pk_col}" = %s'
        try:
            with connection.cursor() as cur:
                cur.execute(sql, params)
        except Exception:
            logger.exception("PG-FTS index_object failed for %s/%s", view.model_label, obj.pk)

    def remove_object(self, view: IndexedView, object_id: int) -> None:
        # The vector lives on the model row; deleting the row drops it.
        pass

    def rebuild(self, view: IndexedView) -> int:
        """Rebuild the search index for a model, then refresh planner stats.

        Two strategies:

        * **Set-based** (default) — when every ``search_field`` maps to a
          local, concrete DB column, recompute the whole table with a single
          ``UPDATE t SET search_vector = setweight(...) || ...``. Seconds
          instead of minutes, and safe to run anytime.
        * **Per-row** — fallback for views whose fields include ``__``-related
          paths or Python properties (e.g. a computed ``phone_search``), which
          have no column to read in SQL. Materializes the pk list up front,
          then loads and indexes in batches with one transaction per batch (no
          open read cursor during writes → no lock contention).

        Either way, ``ANALYZE`` runs at the end: a bulk ``search_vector``
        rewrite leaves stats stale until autovacuum catches up, and the
        planner may seq-scan ``search_vector @@ q`` in the meantime.
        """
        self.ensure_index(view)

        columns = _set_based_columns(view)
        if columns is not None:
            count = self._rebuild_set_based(view, columns)
        else:
            count = self._rebuild_per_row(view)

        self._analyze(view)
        return count

    def _rebuild_set_based(self, view: IndexedView, columns: list[tuple[str, str]]) -> int:
        """Recompute every row's ``search_vector`` in one UPDATE.

        ``columns`` is a list of ``(db_column, weight_label)`` — both derived
        from the model definition (trusted), never user input, so inlining
        them into the statement is safe.
        """
        table = view.model._meta.db_table
        parts = [
            f"setweight(to_tsvector('english', coalesce(\"{col}\"::text, '')), '{label}')"
            for col, label in columns
        ]
        set_expr = " || ".join(parts)
        sql = f'UPDATE "{table}" SET search_vector = {set_expr}'
        with connection.cursor() as cur:
            cur.execute(sql)
            affected = cur.rowcount
        return affected if affected is not None and affected >= 0 else view.model._default_manager.count()

    def _rebuild_per_row(self, view: IndexedView) -> int:
        from django.db import transaction

        pks = list(view.model._default_manager.values_list("pk", flat=True))
        chunk_size = 500
        count = 0
        for start in range(0, len(pks), chunk_size):
            batch = list(view.model._default_manager.filter(pk__in=pks[start : start + chunk_size]))
            with transaction.atomic():
                for obj in batch:
                    self.index_object(view, obj)
            count += len(batch)
        return count

    def _analyze(self, view: IndexedView) -> None:
        table = view.model._meta.db_table
        try:
            with connection.cursor() as cur:
                cur.execute(f'ANALYZE "{table}"')
        except Exception:
            logger.exception("PG-FTS ANALYZE failed for %s", view.model_label)
    # ---- query -----------------------------------------------------------

    def query(
        self,
        view: IndexedView,
        query: str,
        limit: int = 10,
        variant: str = "default",
    ) -> list[SearchHit]:
        from ..query_parser import to_postgres

        translated, search_type = to_postgres(query)
        if not translated:
            return []

        table = view.model._meta.db_table
        pk_col = view.model._meta.pk.column
        tsquery_fn = _TSQUERY_FUNCS.get(search_type, "plainto_tsquery")

        sql = (
            f'SELECT "{pk_col}" AS object_id, ts_rank(search_vector, q) AS rank '
            f"FROM \"{table}\", {tsquery_fn}('english', %s) AS q "
            f"WHERE search_vector @@ q "
            f"ORDER BY rank DESC LIMIT %s"
        )

        with connection.cursor() as cur:
            try:
                cur.execute(sql, [translated, limit])
                rows = cur.fetchall()
            except Exception:
                logger.exception("PG-FTS query failed for %s: %r", view.model_label, query)
                return []

        if not rows:
            return []

        # Re-hydrate objects in one query and preserve rank ordering.
        ids = [r[0] for r in rows]
        rank_by_id = {r[0]: r[1] for r in rows}
        objects_by_id = {o.pk: o for o in view.model._default_manager.filter(pk__in=ids)}

        hits: list[SearchHit] = []
        for obj_id in ids:
            obj = objects_by_id.get(obj_id)
            if not obj:
                continue
            snippet = _build_snippet_pg(view, obj, query)
            hits.append(_make_hit(view, obj, rank=float(rank_by_id[obj_id]), snippet=snippet, variant=variant))
        return hits


# ---- helpers -------------------------------------------------------------


def _gin_index_name(view: IndexedView) -> str:
    """Collision-resistant GIN index name within Postgres' 63-byte identifier
    limit. A plain ``<table>_svec_gin`` prefix-truncation could map two tables
    that share a 63-char prefix to the same index name, silently leaving the
    second table un-indexed (``CREATE INDEX IF NOT EXISTS`` keys on the name).
    Append a hash of the full table name so the result is unique. (Audit L1.)
    """
    table = view.model._meta.db_table
    digest = hashlib.md5(table.encode()).hexdigest()[:12]
    return f"svecgin_{table[:40]}_{digest}"


def _column_exists(table: str, column: str) -> bool:
    """Whether ``table`` already has ``column`` (current schema).

    Mirrors :func:`_index_exists`, and exists for the same reason: so
    ``ensure_index`` issues **no DDL at all** on the overwhelmingly common
    already-provisioned path. ``ADD COLUMN IF NOT EXISTS`` is not free just
    because it is a no-op — Postgres still takes an **AccessExclusiveLock**
    on the table (verified), briefly blocking every reader and writer on a
    live table every time this runs, and it is refused outright when the
    transaction holds pending (deferred) constraint trigger events:
    ``cannot ALTER TABLE "x" because it has pending trigger events``. That
    made ``rebuild_search_index`` uncallable from inside such a transaction.
    """
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s",
                [table, column],
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _index_exists(name: str) -> bool:
    """Whether a relation of kind index named ``name`` exists (current schema)."""
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = %s", [name]
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _clamp_weight(weight_int: int) -> int:
    return max(0, min(int(weight_int), 3))


def _set_based_columns(view: IndexedView) -> list[tuple[str, str]] | None:
    """Return ``[(db_column, weight_label), ...]`` if every search_field is a
    local concrete column — the precondition for the single-UPDATE rebuild.

    Returns ``None`` (→ per-row fallback) if any field is a ``__``-related
    path or a Python property with no backing column, since those can only be
    resolved in Python.
    """
    columns: list[tuple[str, str]] = []
    for field_name in view.fields:
        if "__" in field_name:
            return None
        try:
            model_field = view.model._meta.get_field(field_name)
        except Exception:
            return None  # property / non-field — resolve per-row
        # Concrete, single-column, local fields only (no m2m, no reverse rels).
        if not getattr(model_field, "concrete", False) or model_field.many_to_many:
            return None
        column = getattr(model_field, "column", None)
        if not column:
            return None
        label = _WEIGHT_LABELS.get(_clamp_weight(view.weights.get(field_name, 1)), "C")
        columns.append((column, label))
    return columns or None


def _build_snippet_pg(view: IndexedView, obj: Any, query: str) -> str:
    """Same snippet strategy as SQLite — first matched word, ±40/120 chars."""
    if not view.subtitle_field:
        return ""
    text = str(_resolve_field(obj, view.subtitle_field) or "")
    if not text:
        return ""
    first_word = ""
    for token in query.split():
        cleaned = "".join(c for c in token if c.isalnum())
        if cleaned:
            first_word = cleaned.lower()
            break
    if not first_word:
        return text[:160]
    lower = text.lower()
    idx = lower.find(first_word)
    if idx < 0:
        return text[:160]
    start = max(0, idx - 40)
    end = min(len(text), idx + 120)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
