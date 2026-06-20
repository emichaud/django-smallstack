"""PostgresFTSBackend — full-text search on PostgreSQL via Django's
``django.contrib.postgres.search`` helpers.

Each indexed view gets a denormalized ``search_vector`` column added by
migration (the doctor + docs prompt the user to run makemigrations
after enabling search on a Postgres-backed model). The column is a
``SearchVectorField`` with a GIN index for fast lookup, kept current
via signal handlers in ``apps.search.signals``.

Ranking uses ``ts_rank`` (the standard Postgres FTS scoring) with
weighted fields (A > B > C > D from search_weight).

Because Postgres FTS is config-aware, SmallStack defaults to the
``english`` configuration (stemming, stopwords). Users who want a
different language override per-view via the ``search_config`` class
attribute (not implemented in v0.11.0 — defaults always english).
"""

from __future__ import annotations

import logging
from typing import Any

from .base import IndexedView, SearchHit
from .fallback import _make_hit, _resolve_field

logger = logging.getLogger("smallstack.search")


class PostgresFTSBackend:
    name = "postgresql-fts"

    # PG-FTS expects the search_vector column to exist on the model
    # (created by a migration). We don't auto-create it because Django
    # migrations are the right place; the user runs makemigrations
    # after opting in. The doctor surfaces a clear error if missing.

    # ---- index lifecycle -------------------------------------------------

    def ensure_index(self, view: IndexedView) -> None:
        # No-op: the search_vector column + GIN index are managed by
        # Django migrations, not runtime DDL.
        pass

    def index_object(self, view: IndexedView, obj: Any) -> None:
        """Update the search_vector column for this row.

        Uses Django's ``SearchVector`` to assemble the weighted vector
        from the configured fields. The model must have a
        ``search_vector`` column (added via migration).
        """
        from django.contrib.postgres.search import SearchVector
        from django.db.models import Value
        from django.db.models.functions import Coalesce

        weight_map = {3: "A", 2: "B", 1: "C", 0: "D"}
        parts = []
        for field_name in view.fields:
            weight_int = view.weights.get(field_name, 1)
            weight = weight_map.get(max(0, min(weight_int, 3)), "C")
            parts.append(SearchVector(
                Coalesce(field_name, Value("")),
                weight=weight,
                config="english",
            ))
        if not parts:
            return

        vector = parts[0]
        for p in parts[1:]:
            vector = vector + p

        try:
            view.model.objects.filter(pk=obj.pk).update(search_vector=vector)
        except Exception:
            logger.exception("PG-FTS index_object failed for %s/%s", view.model_label, obj.pk)

    def remove_object(self, view: IndexedView, object_id: int) -> None:
        # When the row is deleted the vector goes with it. Nothing to do.
        pass

    def rebuild(self, view: IndexedView) -> int:
        count = 0
        for obj in view.model.objects.all().iterator(chunk_size=500):
            self.index_object(view, obj)
            count += 1
        return count

    # ---- query -----------------------------------------------------------

    def query(self, view: IndexedView, query: str, limit: int = 10) -> list[SearchHit]:
        from django.contrib.postgres.search import SearchQuery, SearchRank

        from ..query_parser import to_postgres

        translated, search_type = to_postgres(query)
        if not translated:
            return []

        sq = SearchQuery(translated, config="english", search_type=search_type)
        try:
            qs = (
                view.model.objects
                .annotate(_rank=SearchRank("search_vector", sq))
                .filter(search_vector=sq)
                .order_by("-_rank")[:limit]
            )
            results = list(qs)
        except Exception:
            logger.exception("PG-FTS query failed for %s: %r", view.model_label, query)
            return []

        hits: list[SearchHit] = []
        for obj in results:
            snippet = _build_snippet_pg(view, obj, query)
            hits.append(_make_hit(view, obj, rank=float(obj._rank), snippet=snippet))
        return hits


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
