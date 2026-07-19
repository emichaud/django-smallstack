"""FallbackBackend — works on every database, slow at scale.

Used for MySQL and anything else that isn't SQLite or PostgreSQL. No
separate index — runs a multi-field ``__icontains`` OR query at search
time. No ranking (results come back in PK order).

Performance: O(N x M) full table scan per query where M is avg text
length. Fine up to ~5k rows; degrades visibly past 10k. Documented in
``apps/smallstack/docs/search.md`` so users know what they're getting.

The DB-agnostic ``SearchToken`` inverted-index pattern is the obvious
upgrade path here; deferred to v0.12.0 unless someone hits scale.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db.models import Q

from .base import IndexedView, SearchHit

logger = logging.getLogger("smallstack.search")


class FallbackBackend:
    name = "fallback (__icontains)"

    def ensure_index(self, view: IndexedView) -> bool:
        # No index — nothing to ensure; trivially "ready".
        return True

    def index_object(self, view: IndexedView, obj: Any) -> None:
        # No index — nothing to maintain.
        pass

    def remove_object(self, view: IndexedView, object_id: int) -> None:
        pass

    def rebuild(self, view: IndexedView) -> int:
        # Nothing to rebuild; return current row count so the doctor /
        # admin can still show "N indexable rows".
        return view.model.objects.count()

    def query(
        self,
        view: IndexedView,
        query: str,
        limit: int = 10,
        variant: str = "default",
    ) -> list[SearchHit]:
        q = query.strip()
        if not q:
            return []

        # OR across every search_field, __icontains. Doesn't support the
        # full query parser — the operators (quoted phrases, prefix*, OR,
        # NOT) are silently treated as literal text. The query parser
        # documents this limitation.
        filt = Q()
        for field_name in view.fields:
            filt |= Q(**{f"{field_name}__icontains": q})

        qs = view.model.objects.filter(filt).distinct()[:limit]
        return [_make_hit(view, obj, rank=1.0, variant=variant) for obj in qs]


def _make_hit(
    view: IndexedView,
    obj: Any,
    rank: float = 1.0,
    snippet: str = "",
    variant: str = "default",
) -> SearchHit:
    """Convert a Django object to a SearchHit. Shared by all backends.

    Args:
        view: The IndexedView
        obj: The model instance
        rank: Relevance score
        snippet: Text snippet around match
        variant: Output variant name
    """
    # Call transform_hit if view implements SearchBuilder
    extra: dict[str, Any] = {}
    display_val = None
    subtitle_val = None

    if view.has_search_builder and hasattr(view.view_cls, 'transform_hit'):
        try:
            transformed = view.view_cls.transform_hit(obj, variant)
            if isinstance(transformed, dict):
                # Extract display/subtitle from transformed dict
                display_val = transformed.pop("display", None)
                subtitle_val = transformed.pop("subtitle", None)
                extra = transformed  # Rest goes to extra
        except Exception:
            logger.exception("transform_hit failed for %s", view.model_label)

    # Fallback to default field resolution
    if display_val is None:
        display_val = _resolve_field(obj, view.display_field) or str(obj)
    if subtitle_val is None:
        subtitle_val = _resolve_field(obj, view.subtitle_field) or ""

    url: str | None = None
    try:
        url = obj.get_absolute_url()
    except Exception:
        pass

    return SearchHit(
        model_label=view.model_label,
        model_verbose=view.model_verbose,
        object_id=obj.pk,
        display=str(display_val)[:200],
        subtitle=str(subtitle_val)[:200],
        snippet=snippet,
        url=url,
        rank=rank,
        extra=extra,
    )


def _resolve_field(obj: Any, field_path: str | None) -> Any:
    """Walk dotted/dunder path: 'customer__name' → obj.customer.name."""
    if not field_path:
        return None
    parts = field_path.split("__")
    value: Any = obj
    for part in parts:
        if value is None:
            return None
        value = getattr(value, part, None)
    return value
