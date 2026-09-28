"""PostgresFTSBackend — tsvector + GIN, set-based & per-row rebuild, ranked query.

Runs only on Postgres (`TEST_DB=postgres`); skips on SQLite. Closes the review's
F4 gap (postgres_fts.py was at 0% because the default suite is SQLite-only).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from apps.search.backends.base import IndexedView
from apps.search.backends.postgres_fts import (
    PostgresFTSBackend,
    _gin_index_name,
    _index_exists,
    _set_based_columns,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _require_pg():
    if connection.vendor != "postgresql":
        pytest.skip("PostgresFTSBackend requires Postgres (run with TEST_DB=postgres)")


@pytest.fixture
def view():
    return IndexedView(
        view_cls=type("DummyView", (), {}),
        model=get_user_model(),
        fields=["username", "email"],
        display_field="username",
        subtitle_field="email",
    )


@pytest.fixture
def backend(view):
    bk = PostgresFTSBackend()
    bk.ensure_index(view)
    return bk


def test_ensure_index_adds_column_and_gin(backend, view):
    table = view.model._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=%s AND column_name='search_vector'",
            [table],
        )
        assert cur.fetchone() is not None
    assert _index_exists(_gin_index_name(view)) is True
    # Idempotent.
    assert backend.ensure_index(view) is True


def test_index_and_query_roundtrip(backend, view):
    User = get_user_model()
    user = User.objects.create_user(username="pgalpha", email="alpha@example.com")
    backend.index_object(view, user)
    hits = backend.query(view, "pgalpha")
    assert len(hits) == 1
    assert hits[0].object_id == user.pk
    assert hits[0].display == "pgalpha"


def test_query_ranks_and_limits(backend, view):
    User = get_user_model()
    # All three stem to "manag" under the english config, so one query matches
    # all three; limit caps the result.
    for name in ("manage", "manager", "managing"):
        backend.index_object(view, User.objects.create_user(username=name, email=f"{name}@e.com"))
    hits = backend.query(view, "managing", limit=2)
    assert len(hits) == 2
    assert all(h.rank >= 0 for h in hits)


def test_query_empty_returns_empty(backend, view):
    assert backend.query(view, "") == []
    assert backend.query(view, "   ") == []


def test_set_based_rebuild_populates_vectors(backend, view):
    User = get_user_model()
    # bulk_create bypasses signals → no vectors until rebuild.
    User.objects.bulk_create([
        User(username="bulkone", email="b1@example.com"),
        User(username="bulktwo", email="b2@example.com"),
    ])
    assert backend.query(view, "bulkone") == []
    count = backend.rebuild(view)
    assert count >= 2
    with connection.cursor() as cur:
        cur.execute(
            f'SELECT count(*) FROM "{view.model._meta.db_table}" WHERE search_vector IS NULL'
        )
        assert cur.fetchone()[0] == 0
    assert len(backend.query(view, "bulkone")) == 1


def test_per_row_rebuild_for_property_field():
    # `is_authenticated` is a property, not a column → forces the per-row path.
    view = IndexedView(
        view_cls=type("V", (), {}),
        model=get_user_model(),
        fields=["username", "is_authenticated"],
        display_field="username",
    )
    backend = PostgresFTSBackend()
    backend.ensure_index(view)
    assert _set_based_columns(view) is None  # property → not set-based
    get_user_model().objects.bulk_create([get_user_model()(username="proprow", email="p@e.com")])
    assert backend.rebuild(view) >= 1
    assert any(h.display == "proprow" for h in backend.query(view, "proprow"))


def test_set_based_columns_detection(view):
    cols = _set_based_columns(view)  # username + email, both local columns
    assert cols is not None
    assert {c[0] for c in cols} == {"username", "email"}
    # A __ path is not a local column.
    v2 = IndexedView(view_cls=type("V", (), {}), model=get_user_model(), fields=["username__x"])
    assert _set_based_columns(v2) is None


def test_remove_object_is_noop_row_delete_drops_vector(backend, view):
    User = get_user_model()
    user = User.objects.create_user(username="pggamma", email="g@example.com")
    backend.index_object(view, user)
    assert len(backend.query(view, "pggamma")) == 1
    backend.remove_object(view, user.pk)  # no-op — vector lives on the row
    user.delete()
    assert backend.query(view, "pggamma") == []


class TestEnsureIndexIssuesNoDdlWhenProvisioned:
    """Downstream-reported (#6): ``ensure_index`` guarded the GIN index with
    ``_index_exists`` but issued the column ``ALTER TABLE … ADD COLUMN IF NOT
    EXISTS`` unconditionally. Two costs, both verified against Postgres 16:

    1. the no-op ALTER still takes an **AccessExclusiveLock** on the table —
       every ``post_migrate`` and every ``rebuild_search_index`` briefly
       blocks every reader and writer on a live table;
    2. Postgres refuses it outright while the transaction holds pending
       **deferred** constraint trigger events (``cannot ALTER TABLE "x"
       because it has pending trigger events``), which made
       ``rebuild_search_index`` uncallable from such a transaction.

    Note the refined mechanism: plain writes are NOT enough — a
    non-deferrable FK's after-row trigger fires at end of statement, so the
    queue is empty by the next statement. It takes ``SET CONSTRAINTS ALL
    DEFERRED`` (what ``loaddata`` and fixture loading do) or a
    ``DEFERRABLE INITIALLY DEFERRED`` constraint. The fix — mirror the
    existing ``_index_exists`` guard with ``_column_exists`` — makes both
    costs disappear on the already-provisioned path.
    """

    def test_provisioned_ensure_index_issues_no_alter(self, backend, view, monkeypatch):
        """The decisive assertion: zero DDL on the common path."""
        from apps.search.backends import postgres_fts as pg

        statements: list[str] = []
        real_cursor = connection.cursor

        class _SpyCursor:
            def __init__(self, inner):
                self._inner = inner

            def execute(self, sql, params=None):
                statements.append(sql)
                return self._inner.execute(sql, params)

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def __enter__(self):
                self._inner.__enter__()
                return self

            def __exit__(self, *exc):
                return self._inner.__exit__(*exc)

        monkeypatch.setattr(pg.connection, "cursor", lambda: _SpyCursor(real_cursor()))
        assert backend.ensure_index(view) is True  # already provisioned by the fixture
        assert not any("ALTER TABLE" in s.upper() for s in statements), statements
        assert not any("CREATE INDEX" in s.upper() for s in statements), statements

    def test_ensure_index_with_pending_deferred_trigger_events(self, backend, view):
        """The reported failure, reproduced: with deferred constraint events
        queued, the pre-fix unconditional ALTER raised ObjectInUse."""
        from apps.search.registry import get_view
        from apps.smallstack.models import APIToken

        User = get_user_model()
        with connection.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
        owner = User.objects.create_user("deferred-probe", password="p")
        APIToken.create_token(user=owner, name="t")

        token_view = get_view(APIToken)
        assert token_view is not None
        assert backend.ensure_index(token_view) is True  # pre-fix: OperationalError

    def test_rebuild_command_runs_inside_such_a_transaction(self, backend, view):
        from django.core.management import call_command

        User = get_user_model()
        with connection.cursor() as cur:
            cur.execute("SET CONSTRAINTS ALL DEFERRED")
        User.objects.create_user("rebuild-probe", password="p")
        call_command("rebuild_search_index", "accounts.User")  # pre-fix: raised
