"""Search registry — the canonical list of opt-in CRUDViews.

A CRUDView declares ``enable_search = True`` and the search app
registers it here at startup. The registry then drives every other
piece of the search system: index maintenance via signals, MCP tool
generation, the search page's per-model grouping, the dashboard
widget's count.

Lookup is by model label (``"<app_label>.<ModelName>"``) so handlers
that get a Django ``sender`` can find the matching IndexedView quickly.
"""

from __future__ import annotations

import logging
from typing import Iterator

from .backends.base import IndexedView, SearchHit

logger = logging.getLogger("smallstack.search")

_search_registry: dict[str, IndexedView] = {}


def register(view_cls: type) -> IndexedView | None:
    """Register a CRUDView. Idempotent — re-registering is fine.

    Returns the IndexedView or None if the view is malformed (missing
    model / missing fields).
    """
    model = getattr(view_cls, "model", None)
    if model is None:
        logger.warning("Search registration skipped — %s has no model", view_cls)
        return None

    fields = list(getattr(view_cls, "search_fields", None) or [])
    if not fields:
        logger.warning(
            "Search registration skipped — %s has enable_search=True but search_fields is empty",
            view_cls,
        )
        return None

    weights = dict(getattr(view_cls, "search_weight", None) or {})
    display = getattr(view_cls, "search_display", None)
    subtitle = getattr(view_cls, "search_subtitle", None)

    view = IndexedView(
        view_cls=view_cls,
        model=model,
        fields=fields,
        weights=weights,
        display_field=display,
        subtitle_field=subtitle,
    )
    _search_registry[view.model_label] = view

    # Ensure the backend's index structure exists for this view.
    from .backends import get_backend

    backend = get_backend()
    backend.ensure_index(view)

    return view


def unregister(view_cls_or_label: type | str) -> None:
    """Test helper — remove a view from the registry."""
    if isinstance(view_cls_or_label, str):
        _search_registry.pop(view_cls_or_label, None)
        return
    model = getattr(view_cls_or_label, "model", None)
    if model is not None:
        label = f"{model._meta.app_label}.{model.__name__}"
        _search_registry.pop(label, None)


def get_view(model) -> IndexedView | None:
    """Find the IndexedView for a model instance or class (None if not indexed)."""
    if not isinstance(model, type):
        model = type(model)
    label = f"{model._meta.app_label}.{model.__name__}"
    return _search_registry.get(label)


def all_views() -> Iterator[IndexedView]:
    return iter(_search_registry.values())


def view_count() -> int:
    return len(_search_registry)


def get_indexed_sources() -> list[dict]:
    """Structured info on every searchable source.

    Returns one entry per opted-in CRUDView plus one entry for the help
    docs (if installed). Used by the search page's "what's indexed"
    panel and the omnibar's empty-state. Cheap — derived from in-memory
    registry + a count query on the help index.
    """
    sources: list[dict] = []
    for view in _search_registry.values():
        # Sample a couple of records' display values as example searches.
        examples: list[str] = []
        try:
            qs = view.model.objects.all()
            if view.display_field:
                values = qs.values_list(view.display_field, flat=True)[:3]
                examples = [str(v).split()[0] for v in values if v][:2]
        except Exception:
            pass

        sources.append({
            "kind": "model",
            "label": view.model_verbose,
            "model_label": view.model_label,
            "fields": view.fields,
            "examples": examples,
            "url": _list_url_for(view),
        })

    # Append help docs as a separate source.
    try:
        from apps.help.search import help_article_count

        n = help_article_count()
        if n > 0:
            sources.append({
                "kind": "help",
                "label": "Help & Docs",
                "model_label": "help.HelpArticle",
                "fields": ["title", "section", "text"],
                "examples": ["custom palette", "MCP setup", "API tokens"],
                "url": "/smallstack/help/",
                "count": n,
            })
    except Exception:
        pass

    return sources


def _list_url_for(view) -> str | None:
    """Best-effort URL to the model's list page (if a URL name is exposed)."""
    from django.urls import NoReverseMatch, reverse

    url_base = getattr(view.view_cls, "url_base", None)
    if not url_base:
        return None
    candidates = [
        f"{url_base}-list",
        f"{url_base}_list",
    ]
    for name in candidates:
        try:
            return reverse(name)
        except NoReverseMatch:
            continue
    return None


def search_all(query: str, limit_per_model: int = 5) -> list[SearchHit]:
    """Cross-model search — query every registered view + help docs and
    return a combined ranked list.

    Used by the topbar omnibar, the /smallstack/search/ page, and the
    ``search_all`` MCP tool.
    """
    from .backends import get_backend

    backend = get_backend()
    out: list[SearchHit] = []
    for view in _search_registry.values():
        try:
            out.extend(backend.query(view, query, limit=limit_per_model))
        except Exception:
            logger.exception("search_all failed for %s", view.model_label)

    # Help docs are a separate non-CRUDView source. Cheap to query and
    # almost always present in a SmallStack install.
    try:
        from apps.help.search import search_help_articles

        out.extend(search_help_articles(query, limit=limit_per_model))
    except Exception:
        # apps.help missing or query failed — silently skip.
        pass

    # Stable sort by rank descending. Ranks are per-backend; comparison
    # is meaningful WITHIN a backend across models.
    out.sort(key=lambda h: h.rank, reverse=True)
    return out
