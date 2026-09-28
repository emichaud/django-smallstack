"""Help search must not poison the caller's transaction, and must self-heal.

Found by running the full suite against a real Postgres 16 (2026-09-28).
``apps/help/search.py`` probed for its FTS table the "ask forgiveness" way —
``SELECT COUNT(*) FROM help_articles_search_idx`` inside a bare
``except Exception`` — and every raw query in the module sat inside the same
shape. On Postgres a failed statement poisons the WHOLE transaction ("current
transaction is aborted, commands ignored until end of transaction block"), so
the swallowed probe left every later query in the request dead; the visible
failures landed far away (two approvals *search* tests, help-search 500s, and
the activity middleware's log write). SQLite shrugs a failed statement off,
which is why the default dev loop never saw it. Every such cursor now runs in
``transaction.atomic()`` — a savepoint — so the promise the bare except
implies ("this failure is contained") is finally true on both engines.

The second layer: ``_HELP_INDEX_BUILT`` is a process-global memo of *database*
state. Once set, a dropped/restored/rolled-back table left help search
returning nothing until the process restarted. A failed query now clears it.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.help import search as help_search

pytestmark = pytest.mark.django_db


def _drop_help_tables():
    for table in (help_search.HELP_FTS_TABLE, help_search.HELP_CHUNK_TABLE):
        with connection.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{table}"')


@pytest.fixture(autouse=True)
def _reset_memos():
    help_search._HELP_INDEX_BUILT = False
    help_search._HELP_RAG_INDEX_BUILT = False
    yield
    help_search._HELP_INDEX_BUILT = False
    help_search._HELP_RAG_INDEX_BUILT = False


def test_probing_a_missing_index_leaves_the_transaction_usable():
    """The savepoint. On Postgres the un-savepointed probe aborted the
    transaction and every later query raised InFailedSqlTransaction; SQLite
    passes either way — run with TEST_DB=postgres for the real assertion."""
    _drop_help_tables()

    assert help_search._help_index_row_count() == 0
    assert help_search.help_chunk_count() == 0

    # The decisive part: the SAME transaction still answers queries.
    assert get_user_model().objects.count() >= 0


def test_failed_query_clears_the_memo_so_the_next_call_rebuilds():
    """Backend-agnostic: fails on SQLite too before the fix.

    The memo says "built" while the table is gone — without self-healing,
    help search stays empty for the life of the process.
    """
    help_search._HELP_INDEX_BUILT = True
    _drop_help_tables()

    assert help_search.search_help_articles("anything") == []
    assert help_search._HELP_INDEX_BUILT is False  # pre-fix: stayed True forever


def test_rag_failed_query_clears_its_memo_too():
    help_search._HELP_RAG_INDEX_BUILT = True
    _drop_help_tables()

    assert help_search.search_help_chunks("anything") == []
    assert help_search._HELP_RAG_INDEX_BUILT is False


def test_search_still_works_after_the_index_is_rebuilt():
    """Self-heal is not just a flag flip — the next call really does rebuild."""
    _drop_help_tables()
    help_search._HELP_INDEX_BUILT = True
    help_search.search_help_articles("anything")          # fails, clears memo
    assert help_search._HELP_INDEX_BUILT is False

    help_search._ensure_help_index()                       # rebuilds
    assert help_search._help_index_row_count() > 0
    assert get_user_model().objects.count() >= 0           # transaction healthy
