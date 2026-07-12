"""Register the Document model with the SmallStack search engine (``apps.search``).

Runbook rolls its own ``__icontains`` search for the ``/runbook/search/`` page,
but the SmallStack search app provides a much stronger, shared retrieval layer:
BM25-ranked full-text (SQLite FTS5 / Postgres ``ts_rank``), the cross-model
``search_all`` MCP tool + the global omnibar, and a per-model
``search_runbook_documents`` MCP tool. Registering ``Document`` opts it in.

The engine reads plain attributes off a config class — no CRUDView required
(see ``apps.search.registry.register``). Access + per-user scoping reuse the
same ownership rules as the rest of the app via
``permissions.viewable_documents``, so private runbooks never leak into another
user's results (in the omnibar, the search page, *and* the MCP tools).

Everything here is a no-op when ``apps.search`` isn't installed downstream.
"""

from __future__ import annotations

from typing import Any

from .models import Document


class DocumentSearchConfig:
    """Lightweight search-index config for :class:`Document` (not a CRUDView).

    ``apps.search.registry.register`` reads these attributes; ``search_display``
    / ``search_subtitle`` are field/attr paths (not callables).
    """

    model = Document
    search_fields = ["title", "content_text", "description"]
    # Title matches should outrank body matches; description sits between.
    search_weight = {"title": 3, "description": 2, "content_text": 1}
    search_display = "title"
    search_subtitle = "search_subtitle_text"  # the Document @property
    search_access = "authenticated"  # any signed-in user; rows scoped below
    mcp_tool_noun_plural = "runbook_documents"  # → search_runbook_documents

    @staticmethod
    def search_visibility(qs: Any, user: Any) -> Any:
        """Scope hits to what ``user`` may view, and hide archived docs.

        Reuses the app's ownership scoper so search matches the visibility of
        every other surface. (The engine skips this for staff / trusted-internal
        callers; archived docs are still excluded here for everyone else.)
        """
        from . import permissions

        return permissions.viewable_documents(user, qs).filter(is_archived=False)


def register_document() -> bool:
    """Register :class:`Document` with the search engine if it's installed.

    Returns True if registered, False if ``apps.search`` is absent (no-op).
    The FTS index itself is (re)built by the search app's ``post_migrate`` hook;
    backfill existing rows with ``manage.py rebuild_search_index``.
    """
    try:
        from apps.search.registry import register
    except ImportError:
        return False
    register(DocumentSearchConfig)
    return True
