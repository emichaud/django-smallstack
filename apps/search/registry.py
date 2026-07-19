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
from typing import Any, Iterator

from .access import SearchAccess
from .backends.base import IndexedView, SearchHit

logger = logging.getLogger("smallstack.search")

_search_registry: dict[str, IndexedView] = {}

# Callbacks fired with each IndexedView as it is registered. Lets
# order-sensitive consumers — chiefly the MCP tool factory — react to *late*
# registrations from another app's ready() (which runs after search's own
# ready()), instead of only seeing the views present at that instant.
_on_register_hooks: list = []




def _has_search_builder(view_cls: type) -> bool:
    """Check if a view class implements the SearchBuilder protocol.

    Returns True if the view has any SearchBuilder methods.
    All methods are optional — a view is valid if it has ANY of them.
    """
    builder_methods = {
        'get_search_variants',
        'transform_hit',
        'filter_searchable_queryset',
        'get_ranking_weights'
    }
    implemented = {
        m for m in builder_methods
        if hasattr(view_cls, m) and callable(getattr(view_cls, m))
    }
    return len(implemented) > 0


def get_view_by_label(model_label: str) -> IndexedView | None:
    """Get IndexedView by model label (internal helper)."""
    return _search_registry.get(model_label)


def get_search_config(model_label: str) -> dict[str, Any]:
    """Get search configuration for a single model.

    Returns:
        {
            "model_label": "app.Model",
            "fields": ["field1", "field2"],
            "weights": {"field1": 3, "field2": 1},
            "variants": {
                "default": "Full output",
                "summary": "Lightweight version"
            },
            "display_field": "title",
            "subtitle_field": "description",
            "has_search_builder": true,
            "search_access": "staff"
        }
    """
    view = get_view_by_label(model_label)
    if not view:
        return {}

    config: dict[str, Any] = {
        "model_label": view.model_label,
        "fields": view.fields,
        "weights": dict(view.weights) if view.weights else {},
        "display_field": view.display_field,
        "subtitle_field": view.subtitle_field,
        "has_search_builder": view.has_search_builder,
        "search_access": view.access,
        "variants": {},
    }

    if view.has_search_builder:
        try:
            variants = view.view_cls().get_search_variants()
            config["variants"] = variants or {}
        except TypeError as e:
            logger.error(
                "SearchBuilder variant detection failed for %s: %s",
                model_label, e
            )
        except Exception:
            logger.exception("Failed to get variants for %s", model_label)

    return config


def list_search_configs() -> list[dict[str, Any]]:
    """List all search configurations across all registered views.

    Returns a list of dicts, one per view, with full config including variants.
    """
    return [get_search_config(view.model_label) for view in _search_registry.values()]

def add_register_hook(hook) -> None:
    """Register a callback invoked with each ``IndexedView`` as it's registered.

    Idempotent (adding the same hook twice is a no-op). The hook fires for
    *future* ``register()`` calls, not retroactively — call it after processing
    the already-registered views.
    """
    if hook not in _on_register_hooks:
        _on_register_hooks.append(hook)


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

    # Security: default to staff-only (secure default), and pull the
    # optional per-user visibility callback if the CRUDView declared one.
    access = getattr(view_cls, "search_access", SearchAccess.STAFF)
    if not SearchAccess.is_valid(access):
        logger.warning(
            "%s declared search_access=%r — not a valid SearchAccess value; "
            "falling back to STAFF",
            view_cls,
            access,
        )
        access = SearchAccess.STAFF
    visibility = getattr(view_cls, "search_visibility", None)

    view = IndexedView(
        view_cls=view_cls,
        model=model,
        fields=fields,
        weights=weights,
        display_field=display,
        subtitle_field=subtitle,
        access=access,
        visibility=visibility,
    )

    # Detect SearchBuilder protocol
    has_builder = _has_search_builder(view_cls)
    view.has_search_builder = has_builder

    _search_registry[view.model_label] = view

    # Backend index creation is deferred to the post_migrate signal
    # hooked in SearchConfig.ready(). Doing it here would fire DB
    # queries during AppConfig.ready(), which Django warns about.
    # For non-migrate commands, the indexes already exist from a
    # prior `manage.py migrate` (or `make setup`).

    # Notify order-sensitive consumers (e.g. the MCP tool factory) so a view
    # registered after search's ready() still gets its per-model surface.
    for hook in _on_register_hooks:
        try:
            hook(view)
        except Exception:
            logger.exception("search register hook failed for %s", view.model_label)

    return view


def ensure_all_indexes() -> int:
    """Create the backend index structure for every registered view.

    Idempotent — safe to call repeatedly. Returns the number of
    views whose ensure_index succeeded. Hooked to the post_migrate
    signal so it runs after Django finishes initialization.
    """
    from .backends import get_backend

    backend = get_backend()
    ok = 0
    for view in _search_registry.values():
        try:
            if backend.ensure_index(view):
                ok += 1
        except Exception:
            logger.exception("ensure_index failed for %s", view.model_label)
    return ok


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


def _user_can_see(view: IndexedView, user: Any) -> bool:
    """Apply the access-level gate for one indexed view.

    Returns True if ``user`` is allowed to find rows from this view in
    cross-model search, given the view's declared ``search_access``.

    Trusted internal callers pass ``user=None`` and bypass the gate.
    Adding a new SearchAccess level is a single clause here plus a
    new sentinel in :mod:`apps.search.access`.
    """
    if user is None:
        # Trusted internal call (MCP server, management commands, etc.).
        return True
    if getattr(user, "is_staff", False):
        # Staff are exempt — they see everything that's indexed.
        return True

    level = view.access
    if level == SearchAccess.STAFF:
        return False
    if level == SearchAccess.AUTHENTICATED:
        return bool(getattr(user, "is_authenticated", False))
    if level == SearchAccess.ANONYMOUS:
        # Any caller — signed-in or anonymous — passes.
        return True
    # Unknown level (registry validates at register-time, but stay safe).
    return False


def get_indexed_sources(user: Any = None) -> list[dict]:
    """Structured info on every searchable source.

    Returns one entry per opted-in CRUDView plus one entry for the help
    docs (if installed). Used by the search page's "what's indexed"
    panel and the omnibar's empty-state. Cheap — derived from in-memory
    registry + a count query on the help index.

    Security: applies the same per-view access gate as :func:`search_all`.
    Help docs are always returned (intentionally — they are
    documentation and broadly readable).
    """
    sources: list[dict] = []
    for view in _search_registry.values():
        if not _user_can_see(view, user):
            continue
        # Sample recent records to show as a live preview — far more
        # useful than abstract example strings because users see real
        # data they can click into.
        previews: list[dict] = []
        examples: list[str] = []
        total = 0
        try:
            qs = view.model.objects.all()
            total = qs.count()
            recent = list(qs.order_by("-pk")[:5])
            for obj in recent:
                display_val = ""
                if view.display_field:
                    parts = view.display_field.split("__")
                    val = obj
                    for part in parts:
                        if val is None:
                            break
                        val = getattr(val, part, None)
                    display_val = str(val) if val is not None else str(obj)
                else:
                    display_val = str(obj)
                url = None
                try:
                    url = obj.get_absolute_url()
                except Exception:
                    pass
                previews.append({
                    "display": display_val[:80],
                    "url": url,
                    "pk": obj.pk,
                })
            # Derive example queries from the previews — take the first
            # word of each (often a meaningful keyword).
            for p in previews[:3]:
                first_word = p["display"].split()[0] if p["display"] else ""
                if first_word and len(first_word) >= 2:
                    examples.append(first_word)
        except Exception:
            pass

        sources.append({
            "kind": "model",
            "label": view.model_verbose,
            "model_label": view.model_label,
            "fields": view.fields,
            "weights": dict(view.weights) if view.weights else {},
            "display_field": view.display_field,
            "subtitle_field": view.subtitle_field,
            "mcp_tool": _mcp_tool_name_for(view),
            "list_endpoint": _list_url_for(view),
            "examples": examples,
            "previews": previews,
            "total": total,
            "url": _list_url_for(view),
            # Security context for the audit badge on the admin search page.
            "access": view.access,
            "visibility": (
                f"{view.visibility.__module__}.{view.visibility.__qualname__}"
                if view.visibility else None
            ),
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
                "weights": {},
                "display_field": "title",
                "subtitle_field": "section",
                "mcp_tool": "search_help",
                "list_endpoint": "/smallstack/help/",
                "examples": ["custom palette", "MCP setup", "API tokens"],
                "previews": [],
                "total": n,
                "url": "/smallstack/help/",
                "count": n,
                # Help docs are always visible to every caller.
                "access": SearchAccess.ANONYMOUS,
                "visibility": None,
            })
    except Exception:
        pass

    return sources


def _mcp_tool_name_for(view) -> str:
    """Mirror apps.search.mcp_tools._tool_name_for — kept in sync deliberately."""
    custom = getattr(view.view_cls, "mcp_tool_name", None)
    if custom:
        return f"search_{custom}"
    plural = str(view.model._meta.verbose_name_plural).lower().replace(" ", "_")
    return f"search_{plural}"


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


def search_all(query: str, limit_per_model: int = 5, user: Any = None) -> list[SearchHit]:
    """Cross-model search — query every registered view + help docs and
    return a combined ranked list.

    Security model
    --------------
    ``user`` is the request user (or ``None`` for trusted internal callers
    like the MCP server). Two gates apply per registered view, in order:

      1. **Access gate** — :func:`_user_can_see` evaluates the view's
         declared ``search_access`` against the caller. Non-matching
         views are dropped before any query runs (no listing, no
         preview, no leak).

      2. **Visibility filter** — if the view declares a
         ``search_visibility(queryset, user) -> queryset`` callable,
         the surviving hits are re-filtered through it. Hits whose pk
         doesn't survive the filter are dropped.

    Staff and trusted-internal (``user=None``) callers bypass both
    gates. Visibility filters that raise fail safe: the view's hits are
    dropped entirely rather than leaking unfiltered rows.

    Used by the topbar omnibar, the admin /smallstack/search/ page,
    the public /search/ page, and the ``search_all`` MCP tool.
    """
    from .backends import get_backend

    backend = get_backend()
    is_privileged = user is None or bool(getattr(user, "is_staff", False))

    out: list[SearchHit] = []
    for view in _search_registry.values():
        if not _user_can_see(view, user):
            continue

        try:
            hits = backend.query(view, query, limit=limit_per_model)
        except Exception:
            logger.exception("search_all failed for %s", view.model_label)
            continue

        # Visibility filter — scope rows per user when the view declared
        # one. Skipped for staff and trusted-internal callers.
        if hits and not is_privileged and view.visibility is not None:
            try:
                hit_ids = [h.object_id for h in hits]
                visible_qs = view.visibility(view.model.objects.filter(pk__in=hit_ids), user)
                visible_ids = set(visible_qs.values_list("pk", flat=True))
                hits = [h for h in hits if h.object_id in visible_ids]
            except Exception:
                # A misconfigured visibility callback fails safe: drop
                # all hits from this view for this request rather than
                # leaking unfiltered rows.
                logger.exception(
                    "search_visibility failed for %s — dropping all hits this request",
                    view.model_label,
                )
                hits = []

        out.extend(hits)

    # Help docs are a separate non-CRUDView source. Treated as broadly
    # readable (intentionally so — they're documentation). Available to
    # any authenticated user and to anonymous-trusted callers.
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
