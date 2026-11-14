"""Tests for the lexical-RAG help chunker.

Covers apps/help/chunking.py (pure chunking + raw-markdown discovery) and the
passage index in apps/help/search.py (sync_help_rag_index / search_help_chunks).
Mirrors test_help_search.py conventions: the FTS parts run on SQLite and
Postgres and skip on other engines; the pure chunker tests need no database.
"""

from __future__ import annotations

import pytest
from django.db import connection

from apps.help.chunking import chunk_markdown


def _has_chunk_fts() -> bool:
    """Passage FTS is real on SQLite (FTS5) and Postgres (tsvector+GIN)."""
    return connection.vendor in ("sqlite", "postgresql")


class TestChunkMarkdown:
    """Pure chunker behavior — no database, no dependencies."""

    def test_empty_text_yields_nothing(self):
        assert list(chunk_markdown("", source="s")) == []

    def test_no_headings_is_one_chunk(self):
        text = "just some text with no headings at all"
        chunks = list(chunk_markdown(text, source="s"))
        assert len(chunks) == 1
        assert chunks[0]["heading_path"] == ""
        assert chunks[0]["text"] == text

    def test_splits_on_headings(self):
        text = "# A\naaa\n## B\nbbb\n"
        bodies = {c["text"] for c in chunk_markdown(text, source="s")}
        assert "aaa" in bodies
        assert "bbb" in bodies

    def test_heading_path_builds_breadcrumb(self):
        text = "# A\naaa\n## B\nbbb\n### C\nccc\n## D\nddd\n"
        paths = [c["heading_path"] for c in chunk_markdown(text, source="s")]
        assert "A" in paths
        assert "A › B" in paths
        assert "A › B › C" in paths
        # A sibling H2 pops the deeper H3 off the trail.
        assert "A › D" in paths

    def test_preamble_before_first_heading_is_captured(self):
        text = "intro para\n# H\nbody"
        pre = [c for c in chunk_markdown(text, source="s") if c["heading_path"] == ""]
        assert pre and "intro para" in pre[0]["text"]

    def test_long_section_windows_with_overlap(self):
        body = "".join(f"{i:04d}" for i in range(500))  # 2000 deterministic chars
        text = "# H\n" + body
        chunks = list(chunk_markdown(text, source="s", max_chars=1000, overlap=200))
        assert len(chunks) > 1
        assert all(c["heading_path"] == "H" for c in chunks)
        assert all(len(c["text"]) <= 1000 for c in chunks)
        # Consecutive windows overlap by exactly `overlap` characters.
        assert chunks[0]["text"][-200:] == chunks[1]["text"][:200]

    def test_source_is_carried_on_every_chunk(self):
        text = "# A\naaa\n## B\nbbb\n"
        assert all(c["source"] == "docs/x" for c in chunk_markdown(text, source="docs/x"))


class TestIterHelpMarkdown:
    """Raw-markdown discovery — the ingestion source for the index."""

    @pytest.mark.django_db
    def test_yields_intact_markdown_with_headings(self):
        from apps.help.chunking import iter_help_markdown

        docs = list(iter_help_markdown())
        assert docs, "expected bundled help docs to be discoverable"
        assert set(docs[0]) >= {"source", "section", "title", "text"}
        # Raw markdown keeps its ATX headings (build_search_index strips them),
        # which is what the chunker needs to build citation trails.
        assert any("#" in doc["text"] for doc in docs)


class TestHelpRagIndex:
    """Passage index + query — SQLite FTS5 and Postgres tsvector+GIN."""

    @pytest.mark.django_db
    def test_sync_returns_chunk_count(self):
        from apps.help.search import sync_help_rag_index

        count = sync_help_rag_index()
        if _has_chunk_fts():
            assert count >= 1
        else:
            assert count == 0

    @pytest.mark.django_db
    def test_chunk_index_is_finer_than_article_index(self):
        if not _has_chunk_fts():
            pytest.skip("FTS requires SQLite or Postgres")
        from apps.help.search import sync_help_index, sync_help_rag_index

        articles = sync_help_index()
        chunks = sync_help_rag_index()
        # Passages are per-section, so there are at least as many as articles.
        assert chunks >= articles >= 1

    @pytest.mark.django_db
    def test_search_returns_cited_passages(self):
        if not _has_chunk_fts():
            pytest.skip("FTS requires SQLite or Postgres")
        from apps.help.search import search_help_chunks, sync_help_rag_index

        sync_help_rag_index()
        hits = search_help_chunks("palette", limit=5)
        assert hits, "expected 'palette' to match the theming docs"
        top = hits[0]
        assert top.model_label == "help.HelpChunk"
        assert top.url is not None
        # The citation trail is exposed to the caller (MCP/LLM) via extra.
        assert "heading_path" in top.extra

    @pytest.mark.django_db
    def test_empty_query_returns_empty(self):
        from apps.help.search import search_help_chunks

        assert search_help_chunks("") == []
        assert search_help_chunks("   ") == []
