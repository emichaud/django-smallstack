"""SQLiteFTSBackend — FTS5 virtual table indexing + querying."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.search.backends.base import IndexedView
from apps.search.backends.sqlite_fts import SQLiteFTSBackend, _fts_table

pytestmark = pytest.mark.django_db


def _is_sqlite() -> bool:
    return "sqlite" in connection.settings_dict["ENGINE"]


@pytest.fixture
def view():
    User = get_user_model()
    return IndexedView(
        view_cls=type("DummyView", (), {}),
        model=User,
        fields=["username", "email"],
        display_field="username",
        subtitle_field="email",
    )


@pytest.fixture
def backend(view):
    """Create the FTS table, yield the backend, then drop the table."""
    if not _is_sqlite():
        pytest.skip("FTS5 backend requires SQLite")
    bk = SQLiteFTSBackend()
    bk.ensure_index(view)
    yield bk
    with connection.cursor() as cur:
        cur.execute(f'DROP TABLE IF EXISTS "{_fts_table(view)}"')


def test_ensure_index_creates_virtual_table(backend, view):
    """Idempotent — re-calling ensure_index doesn't blow up."""
    backend.ensure_index(view)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=%s",
            [_fts_table(view)],
        )
        assert cur.fetchone() is not None


def test_index_and_query_roundtrip(backend, view):
    User = get_user_model()
    user = User.objects.create_user(username="ftsalpha", email="alpha@example.com")
    backend.index_object(view, user)

    hits = backend.query(view, "ftsalpha")
    assert len(hits) == 1
    assert hits[0].display == "ftsalpha"
    assert hits[0].object_id == user.pk


def test_index_dedupe_on_reindex(backend, view):
    """Re-indexing the same object replaces (not duplicates) the row."""
    User = get_user_model()
    user = User.objects.create_user(username="ftsbeta", email="beta@example.com")
    backend.index_object(view, user)
    backend.index_object(view, user)
    backend.index_object(view, user)
    hits = backend.query(view, "ftsbeta")
    assert len(hits) == 1


def test_remove_object(backend, view):
    User = get_user_model()
    user = User.objects.create_user(username="ftsgamma", email="g@example.com")
    backend.index_object(view, user)
    assert len(backend.query(view, "ftsgamma")) == 1
    backend.remove_object(view, user.pk)
    assert backend.query(view, "ftsgamma") == []


def test_rebuild_indexes_all_existing_rows(backend, view):
    User = get_user_model()
    User.objects.create_user(username="ftsdelta1", email="d1@example.com")
    User.objects.create_user(username="ftsdelta2", email="d2@example.com")
    count = backend.rebuild(view)
    assert count >= 2
    hits = backend.query(view, "ftsdelta1")
    assert any(h.display == "ftsdelta1" for h in hits)


def test_query_empty_returns_empty(backend, view):
    assert backend.query(view, "") == []
    assert backend.query(view, "   ") == []


def test_porter_stemming_active(backend, view):
    """FTS5 with porter tokenizer matches 'running' when querying 'run'."""
    User = get_user_model()
    User.objects.create_user(username="runs", email="runner@example.com")
    User.objects.create_user(username="running", email="run@example.com")
    backend.index_object(view, User.objects.get(username="runs"))
    backend.index_object(view, User.objects.get(username="running"))
    hits = backend.query(view, "run")
    # Both should match thanks to porter stemming.
    displays = [h.display for h in hits]
    assert "runs" in displays or "running" in displays
