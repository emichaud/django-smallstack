"""Tests for the search_help_docs MCP tool (passage-level help RAG).

search_help_docs exposes apps/help/search.py:search_help_chunks over MCP.
Unlike search_help (whole articles), it returns focused, cited passages.
Help docs are intentionally always-visible, so there is no access gate to
assert here — these tests pin registration, output shape, and that the
citation trail reaches the caller. The FTS parts run on SQLite and Postgres,
mirroring test_help_search.py.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.mcp.server import (
    TOOL_HANDLERS,
    TOOL_REGISTRY,
    ToolContext,
    reset_context,
    set_context,
)

pytestmark = pytest.mark.django_db


def _has_chunk_fts() -> bool:
    """Passage FTS is real on SQLite (FTS5) and Postgres (tsvector+GIN)."""
    return connection.vendor in ("sqlite", "postgresql")


@pytest.fixture(autouse=True)
def _ensure_search_tools_registered():
    """Re-register search MCP tools each test.

    The MCP suite's clean_registry fixture wipes TOOL_HANDLERS/TOOL_REGISTRY,
    so without this the tool's presence would depend on test ordering.
    register_search_tools() is idempotent.
    """
    from apps.search.mcp_tools import register_search_tools

    register_search_tools()


def _call_handler(name, args, *, user=None):
    """Invoke an MCP tool handler with a given calling user."""
    token = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(token)


def test_tool_is_registered_readonly():
    assert "search_help_docs" in TOOL_REGISTRY
    td = TOOL_REGISTRY["search_help_docs"]
    assert td.requires_access == "readonly"
    assert "query" in td.input_schema["properties"]
    assert td.input_schema["required"] == ["query"]


def test_empty_query_returns_empty():
    assert _call_handler("search_help_docs", {"query": "  "}) == {"results": []}


def test_returns_cited_passages():
    if not _has_chunk_fts():
        pytest.skip("Help RAG FTS requires SQLite or Postgres")
    from apps.help.search import sync_help_rag_index

    sync_help_rag_index()
    out = _call_handler("search_help_docs", {"query": "palette", "limit": 3})
    assert out["mode"] == "lexical"
    assert out["results"], "expected 'palette' to match the theming docs"
    top = out["results"][0]
    # Citation trail + source + url reach the calling model via as_dict().
    assert top["model_label"] == "help.HelpChunk"
    assert top["heading_path"]
    assert top["url"]


def test_readonly_non_staff_user_is_served():
    """Help docs are always visible — a readonly, non-staff caller gets results."""
    if not _has_chunk_fts():
        pytest.skip("Help RAG FTS requires SQLite or Postgres")
    from apps.help.search import sync_help_rag_index

    sync_help_rag_index()
    user = get_user_model().objects.create_user(username="reader", password="x")
    out = _call_handler("search_help_docs", {"query": "palette"}, user=user)
    assert out["results"]
