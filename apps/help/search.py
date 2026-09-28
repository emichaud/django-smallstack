"""Help-article search adapter.

Bridges the existing markdown-based help system (``apps/help/utils.py``)
into the unified search backend. Help articles aren't Django models —
they're markdown files on disk — so they live as a separate "source"
inside the search system, queried alongside CRUDView results.

The shape of the help-article search table mirrors the FTS5 model
tables but with a fixed schema (slug, section, title, text). Backend
selection follows the same engine-detection logic as model search.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.search.backends.base import SearchHit

logger = logging.getLogger("smallstack.search.help")

# Single virtual table for help articles. Keyed by (section, slug) so
# the same slug can exist in different sections without colliding.
HELP_FTS_TABLE = "help_articles_search_idx"


# GIN index name for the Postgres help-article table.
HELP_PG_GIN = f"{HELP_FTS_TABLE}_gin"


def sync_help_index() -> int:
    """Rebuild the help-article search index from filesystem markdown.

    Returns the article count indexed. Idempotent — drops and refills the
    table. Cheap (under ~100 articles in a typical install). Uses SQLite
    FTS5 or a Postgres ``tsvector`` + GIN table depending on the engine, so
    help search is a real indexed source on both — not a special-cased
    Python scan on Postgres. Other engines have no help FTS table; queries
    fall back to an in-memory scan (fine at this article count).
    """
    from django.db import connection

    from apps.help.utils import build_search_index, clear_search_index_cache

    # A manual sync means "pick up whatever is on disk now" — drop the memo.
    clear_search_index_cache()

    articles = build_search_index()
    if not articles:
        return 0

    if connection.vendor == "postgresql":
        return _sync_help_index_pg(articles)
    if connection.vendor == "sqlite":
        return _sync_help_index_sqlite(articles)

    logger.info(
        "Help search index sync skipped on %s — no FTS table for this engine; "
        "queries use the in-memory fallback scan.",
        connection.vendor,
    )
    return 0


def _sync_help_index_sqlite(articles) -> int:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            f'CREATE VIRTUAL TABLE IF NOT EXISTS "{HELP_FTS_TABLE}" USING fts5'
            f'("slug" UNINDEXED, "section" UNINDEXED, "title", "text",'
            f' tokenize="porter unicode61")'
        )
        cur.execute(f'DELETE FROM "{HELP_FTS_TABLE}"')
        for article in articles:
            cur.execute(
                f'INSERT INTO "{HELP_FTS_TABLE}" ("slug", "section", "title", "text") '
                f"VALUES (%s, %s, %s, %s)",
                [
                    article.get("slug", ""),
                    article.get("section", ""),
                    article.get("title", ""),
                    article.get("text", ""),
                ],
            )
    return len(articles)


def _sync_help_index_pg(articles) -> int:
    """Build the Postgres help-article FTS table (title weighted A, body B)."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{HELP_FTS_TABLE}" '
            f"(slug text, section text, title text, body text, search_vector tsvector)"
        )
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS "{HELP_PG_GIN}" '
            f'ON "{HELP_FTS_TABLE}" USING GIN (search_vector)'
        )
        cur.execute(f'TRUNCATE "{HELP_FTS_TABLE}"')
        for article in articles:
            cur.execute(
                f'INSERT INTO "{HELP_FTS_TABLE}" (slug, section, title, body, search_vector) '
                f"VALUES (%s, %s, %s, %s, "
                f"setweight(to_tsvector('english', %s), 'A') || "
                f"setweight(to_tsvector('english', %s), 'B'))",
                [
                    article.get("slug", ""),
                    article.get("section", ""),
                    article.get("title", ""),
                    article.get("text", ""),
                    article.get("title", ""),
                    article.get("text", ""),
                ],
            )
    return len(articles)


_HELP_INDEX_BUILT = False


def _forget_help_index() -> None:
    """Clear the built-memo so the next query rebuilds.

    The memo is process-global, but "is the index table there?" is *database*
    state: a restored or reset database — or a rolled-back transaction —
    leaves the memo lying, and help search then returns nothing until the
    process restarts. Called whenever a query against the index fails.
    """
    global _HELP_INDEX_BUILT
    _HELP_INDEX_BUILT = False


def _ensure_help_index() -> None:
    """Lazily populate the help-article index on first query.

    Saves the per-boot cost of always running sync_help_index() in
    HelpConfig.ready() — tests don't pay it; production pays it once
    on the first call. The management command sync_help_index forces
    a rebuild. Checks the *index table's* own row count (not the doc
    count), so it also builds the index on Postgres, where the two differ.
    """
    global _HELP_INDEX_BUILT
    if _HELP_INDEX_BUILT:
        return
    if _help_index_row_count() > 0:
        _HELP_INDEX_BUILT = True
        return
    try:
        # Savepoint for the same reason as _help_index_row_count: a failed
        # build must not poison the caller's transaction.
        with transaction.atomic():
            sync_help_index()
    except Exception:
        logger.exception("Lazy help-index sync failed")
    _HELP_INDEX_BUILT = True


def _help_index_row_count() -> int:
    """Rows in the engine's help FTS table (0 if the table doesn't exist yet)."""
    from django.db import connection

    if connection.vendor not in ("sqlite", "postgresql"):
        return 0
    # A savepoint, not decoration: on Postgres a failed statement poisons the
    # WHOLE transaction ("current transaction is aborted"), so probing for a
    # missing table by running a query and catching the error left every
    # later query in the request dead — and the bare except hid it. The
    # visible failure surfaced far away (help-search 500s, and every
    # subsequent ORM call in the same request). SQLite just shrugs, which is
    # why the default dev loop never saw it.
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{HELP_FTS_TABLE}"')
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def search_help_articles(query: str, limit: int = 10) -> list[SearchHit]:
    """Query the help-article index. Returns SearchHits with help URLs."""
    from django.db import connection

    if connection.vendor == "postgresql":
        return _search_help_pg(query, limit)
    if connection.vendor != "sqlite":
        return _fallback_scan(query, limit)

    from apps.search.query_parser import to_fts5

    _ensure_help_index()

    translated = to_fts5(query)
    if not translated:
        return []

    sql = (
        f'SELECT slug, section, title, snippet("{HELP_FTS_TABLE}", 3, "", "", "…", 12) AS snip, '
        f'-bm25("{HELP_FTS_TABLE}", 0.0, 0.0, 3.0, 1.0) AS rank '
        f'FROM "{HELP_FTS_TABLE}" WHERE "{HELP_FTS_TABLE}" MATCH %s '
        f"ORDER BY rank DESC LIMIT %s"
    )
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [translated, limit])
            rows = cur.fetchall()
    except Exception:
        logger.exception("Help search query failed: %r", query)
        _forget_help_index()
        return []

    hits: list[SearchHit] = []
    for slug, section, title, snip, rank in rows:
        url = _resolve_help_url(slug, section)
        hits.append(SearchHit(
            model_label="help.HelpArticle",
            model_verbose="Help & Docs",
            object_id=0,
            display=title or slug,
            subtitle=section,
            snippet=snip or "",
            url=url,
            rank=float(rank),
        ))
    return hits


_PG_TSQUERY_FUNCS = {
    "plain": "plainto_tsquery",
    "phrase": "phraseto_tsquery",
    "raw": "to_tsquery",
}


def _search_help_pg(query: str, limit: int) -> list[SearchHit]:
    """Query the Postgres help-article FTS table (GIN-indexed ts_rank).

    The snippet is built in Python from the stored body — same window style
    as the SQLite/fallback paths — so the SearchHit shape is identical across
    engines and the UI never branches on which backend answered.
    """
    from django.db import connection

    from apps.search.query_parser import to_postgres

    _ensure_help_index()

    translated, search_type = to_postgres(query)
    if not translated:
        return []
    tsquery_fn = _PG_TSQUERY_FUNCS.get(search_type, "plainto_tsquery")

    sql = (
        f"SELECT slug, section, title, body, ts_rank(search_vector, q) AS rank "
        f"FROM \"{HELP_FTS_TABLE}\", {tsquery_fn}('english', %s) AS q "
        f"WHERE search_vector @@ q ORDER BY rank DESC LIMIT %s"
    )
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [translated, limit])
            rows = cur.fetchall()
    except Exception:
        logger.exception("Help search query failed (pg): %r", query)
        _forget_help_index()  # the index may be gone; rebuild on the next call
        return []

    q_lower = query.lower().strip()
    hits: list[SearchHit] = []
    for slug, section, title, body, rank in rows:
        url = _resolve_help_url(slug, section)
        hits.append(SearchHit(
            model_label="help.HelpArticle",
            model_verbose="Help & Docs",
            object_id=0,
            display=title or slug,
            subtitle=section,
            snippet=_extract_window(body or "", q_lower),
            url=url,
            rank=float(rank),
        ))
    return hits


def _fallback_scan(query: str, limit: int) -> list[SearchHit]:
    """In-memory scan for engines with no help FTS table. Cheap at ~100 articles."""
    from apps.help.utils import build_search_index

    q = query.lower().strip()
    if not q:
        return []

    hits: list[SearchHit] = []
    for article in build_search_index():
        title = article.get("title", "") or ""
        text = article.get("text", "") or ""
        score = 0
        if q in title.lower():
            score += 3
        if q in text.lower():
            score += 1
        if score:
            url = _resolve_help_url(article.get("slug", ""), article.get("section", ""))
            hits.append(SearchHit(
                model_label="help.HelpArticle",
                model_verbose="Help & Docs",
                object_id=0,
                display=title or article.get("slug", ""),
                subtitle=article.get("section", ""),
                snippet=_extract_window(text, q),
                url=url,
                rank=float(score),
            ))
    hits.sort(key=lambda h: h.rank, reverse=True)
    return hits[:limit]


def _resolve_help_url(slug: str, section: str) -> str | None:
    from django.urls import NoReverseMatch, reverse

    try:
        if section:
            return reverse("help:section_detail", kwargs={"section": section, "slug": slug})
        return reverse("help:detail", kwargs={"slug": slug})
    except NoReverseMatch:
        return None


def _extract_window(text: str, q: str) -> str:
    lower = text.lower()
    idx = lower.find(q)
    if idx < 0:
        return text[:160]
    start = max(0, idx - 40)
    end = min(len(text), idx + 120)
    out = text[start:end]
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def help_article_count() -> int:
    """Number of articles currently indexed.

    Cheap on every engine that HAS an index. The old guard here was an
    ENGINE-string check — the last one in this module, everything else moved
    to ``connection.vendor`` — written when only SQLite had a help FTS table:
    it sent **every non-SQLite engine, i.e. production-on-Postgres**, through
    ``build_search_index()``, a full re-read and re-render of every markdown
    doc (~1.5s locally, seconds on a small box). ``@lru_cache`` bounded that,
    but ``sync_help_index()`` *clears* the cache, so each lazy index build
    made the next count pay the parse again. Postgres has had a real
    ``help_articles_search_idx`` since v0.21.9, so it takes the COUNT like
    SQLite — and the number now means the same thing on both engines (rows in
    the index, which is what "currently indexed" claims). Engines with no FTS
    table still have nowhere else to look. (Downstream-reported.)
    """
    from django.db import connection

    if connection.vendor not in ("sqlite", "postgresql"):
        from apps.help.utils import build_search_index

        return len(build_search_index())
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{HELP_FTS_TABLE}"')
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Lexical RAG — passage-level (chunk) index over the SAME help markdown.
#
# HELP_FTS_TABLE (above) holds one row per ARTICLE — good for "take me to the
# page." This table holds one row per markdown SECTION so a tool/LLM gets a
# focused, cited PASSAGE instead of a whole document. Same engines as the
# article index (SQLite FTS5 / Postgres tsvector+GIN), same SearchHit output
# shape, zero extra dependencies.
#
# The semantic half of RAG (embeddings + vector KNN) is intentionally NOT here.
# It can be layered on later behind the same SearchHit contract — callers of
# search_help_chunks() can't tell lexical from semantic, which is exactly what
# lets that upgrade happen without touching downstream code.
# ---------------------------------------------------------------------------

HELP_CHUNK_TABLE = "help_chunks_search_idx"
# GIN index name for the Postgres passage (chunk) table.
HELP_CHUNK_PG_GIN = f"{HELP_CHUNK_TABLE}_gin"


def sync_help_rag_index() -> int:
    """Rebuild the passage-level help index from filesystem markdown.

    Returns the number of chunks indexed. Idempotent — drops and refills the
    table. Uses SQLite FTS5 or a Postgres ``tsvector`` + GIN table depending on
    the engine (mirroring sync_help_index), so the ``search_help_docs`` MCP
    tool works on both. Other engines have no chunk table and that tool returns
    empty there.
    """
    from django.db import connection

    from apps.help.chunking import chunk_markdown, iter_help_markdown

    chunks = [
        {
            "source": doc["source"],
            "section": doc["section"],
            "heading_path": ch["heading_path"],
            "text": ch["text"],
        }
        for doc in iter_help_markdown()
        for ch in chunk_markdown(doc["text"], source=doc["source"])
    ]
    if not chunks:
        return 0

    if connection.vendor == "postgresql":
        return _sync_help_rag_index_pg(chunks)
    if connection.vendor == "sqlite":
        return _sync_help_rag_index_sqlite(chunks)

    logger.info(
        "Help RAG index sync skipped on %s — no FTS table for this engine.",
        connection.vendor,
    )
    return 0


def _sync_help_rag_index_sqlite(chunks) -> int:
    from django.db import connection

    with connection.cursor() as cur:
        # Columns: source(0) section(1) heading_path(2) text(3).
        # source/section are UNINDEXED — carried for URL resolution only.
        cur.execute(
            f'CREATE VIRTUAL TABLE IF NOT EXISTS "{HELP_CHUNK_TABLE}" USING fts5'
            f'("source" UNINDEXED, "section" UNINDEXED, "heading_path", "text",'
            f' tokenize="porter unicode61")'
        )
        cur.execute(f'DELETE FROM "{HELP_CHUNK_TABLE}"')
        for ch in chunks:
            cur.execute(
                f'INSERT INTO "{HELP_CHUNK_TABLE}" '
                f'("source", "section", "heading_path", "text") '
                f"VALUES (%s, %s, %s, %s)",
                [ch["source"], ch["section"], ch["heading_path"], ch["text"]],
            )
    return len(chunks)


def _sync_help_rag_index_pg(chunks) -> int:
    """Build the Postgres passage table (heading_path weighted A, body B)."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{HELP_CHUNK_TABLE}" '
            f"(source text, section text, heading_path text, body text, search_vector tsvector)"
        )
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS "{HELP_CHUNK_PG_GIN}" '
            f'ON "{HELP_CHUNK_TABLE}" USING GIN (search_vector)'
        )
        cur.execute(f'TRUNCATE "{HELP_CHUNK_TABLE}"')
        for ch in chunks:
            cur.execute(
                f'INSERT INTO "{HELP_CHUNK_TABLE}" '
                f"(source, section, heading_path, body, search_vector) "
                f"VALUES (%s, %s, %s, %s, "
                f"setweight(to_tsvector('english', %s), 'A') || "
                f"setweight(to_tsvector('english', %s), 'B'))",
                [
                    ch["source"],
                    ch["section"],
                    ch["heading_path"],
                    ch["text"],
                    ch["heading_path"],
                    ch["text"],
                ],
            )
    return len(chunks)


_HELP_RAG_INDEX_BUILT = False


def _forget_help_rag_index() -> None:
    """Clear the RAG built-memo — see :func:`_forget_help_index`."""
    global _HELP_RAG_INDEX_BUILT
    _HELP_RAG_INDEX_BUILT = False


def _ensure_help_rag_index() -> None:
    """Lazily populate the chunk index on first query (mirrors _ensure_help_index)."""
    global _HELP_RAG_INDEX_BUILT
    if _HELP_RAG_INDEX_BUILT:
        return
    if help_chunk_count() > 0:
        _HELP_RAG_INDEX_BUILT = True
        return
    try:
        with transaction.atomic():  # see _ensure_help_index
            sync_help_rag_index()
    except Exception:
        logger.exception("Lazy help-RAG-index sync failed")
    _HELP_RAG_INDEX_BUILT = True


def help_chunk_count() -> int:
    """Number of passages currently indexed (0 if the table doesn't exist yet)."""
    from django.db import connection

    if connection.vendor not in ("sqlite", "postgresql"):
        return 0
    # A savepoint, not decoration: on Postgres a failed statement poisons the
    # WHOLE transaction ("current transaction is aborted"), so probing for a
    # missing table by running a query and catching the error left every
    # later query in the request dead — and the bare except hid it. The
    # visible failure surfaced far away (help-search 500s, and every
    # subsequent ORM call in the same request). SQLite just shrugs, which is
    # why the default dev loop never saw it.
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{HELP_CHUNK_TABLE}"')
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def search_help_chunks(query: str, limit: int = 5) -> list[SearchHit]:
    """Query the passage index. Returns SearchHits citing the source section.

    Same output contract as search_help_articles() — the display line is the
    heading trail (the citation), the snippet is the matched passage text. A
    future semantic tier returns the same SearchHit shape, so the MCP tool,
    API, and UI never branch on which engine answered.
    """
    from django.db import connection

    if connection.vendor == "postgresql":
        return _search_help_chunks_pg(query, limit)
    if connection.vendor != "sqlite":
        return []

    from apps.search.query_parser import to_fts5

    _ensure_help_rag_index()

    translated = to_fts5(query)
    if not translated:
        return []

    # Weight heading_path (col 2) above body text (col 3) in bm25; the two
    # UNINDEXED columns get 0.0. snippet() pulls from the text column (index 3).
    sql = (
        f'SELECT source, section, heading_path, '
        f'snippet("{HELP_CHUNK_TABLE}", 3, "", "", "…", 24) AS snip, '
        f'-bm25("{HELP_CHUNK_TABLE}", 0.0, 0.0, 2.0, 1.0) AS rank '
        f'FROM "{HELP_CHUNK_TABLE}" WHERE "{HELP_CHUNK_TABLE}" MATCH %s '
        f"ORDER BY rank DESC LIMIT %s"
    )
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [translated, limit])
            rows = cur.fetchall()
    except Exception:
        logger.exception("Help RAG search query failed: %r", query)
        _forget_help_rag_index()
        return []

    hits: list[SearchHit] = []
    for source, section, heading_path, snip, rank in rows:
        url = _resolve_help_url(source, section)
        hits.append(SearchHit(
            model_label="help.HelpChunk",
            model_verbose="Help & Docs",
            object_id=0,
            display=heading_path or source,
            subtitle=source,
            snippet=snip or "",
            url=url,
            rank=float(rank),
            extra={"source": source, "section": section, "heading_path": heading_path},
        ))
    return hits


def _search_help_chunks_pg(query: str, limit: int) -> list[SearchHit]:
    """Query the Postgres passage table (heading_path weighted above body).

    Snippet built in Python from the stored body — same window as the
    SQLite path — so the SearchHit shape is identical across engines and the
    ``search_help_docs`` MCP tool never branches on which backend answered.
    """
    from django.db import connection

    from apps.search.query_parser import to_postgres

    _ensure_help_rag_index()

    translated, search_type = to_postgres(query)
    if not translated:
        return []
    tsquery_fn = _PG_TSQUERY_FUNCS.get(search_type, "plainto_tsquery")

    sql = (
        f"SELECT source, section, heading_path, body, ts_rank(search_vector, q) AS rank "
        f"FROM \"{HELP_CHUNK_TABLE}\", {tsquery_fn}('english', %s) AS q "
        f"WHERE search_vector @@ q ORDER BY rank DESC LIMIT %s"
    )
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(sql, [translated, limit])
            rows = cur.fetchall()
    except Exception:
        logger.exception("Help RAG search query failed (pg): %r", query)
        _forget_help_rag_index()
        return []

    q_lower = query.lower().strip()
    hits: list[SearchHit] = []
    for source, section, heading_path, body, rank in rows:
        url = _resolve_help_url(source, section)
        hits.append(SearchHit(
            model_label="help.HelpChunk",
            model_verbose="Help & Docs",
            object_id=0,
            display=heading_path or source,
            subtitle=source,
            snippet=_extract_window(body or "", q_lower),
            url=url,
            rank=float(rank),
            extra={"source": source, "section": section, "heading_path": heading_path},
        ))
    return hits
