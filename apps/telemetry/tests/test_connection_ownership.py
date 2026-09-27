"""_write() must only manage the connection it owns.

Downstream-reported: the synchronous path (``flush()`` — used by
``start_worker=False`` mode, tests, and ``logging.shutdown()`` at interpreter
exit) runs on the CALLER's thread, borrowing the caller's connection — yet
``_write()`` unconditionally called ``close_old_connections()`` and, on error,
``connection.close()``. Correct on the worker thread (thread-local connection
it owns); on the sync path it closes a live request's / test transaction's
connection on Postgres. SQLite's shared in-memory connection makes both calls
no-ops, hiding the defect on the default backend — same category as the
search-signal migration bug.
"""

from __future__ import annotations

import logging

import pytest

from apps.telemetry.handlers import DatabaseLogHandler
from apps.telemetry.models import LogRecord

pytestmark = pytest.mark.django_db


def _record(msg="hello"):
    return logging.LogRecord(
        name="apps.demo", level=logging.WARNING, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


@pytest.fixture
def sync_handler():
    handler = DatabaseLogHandler(level="WARNING", start_worker=False)
    yield handler
    handler.close()


def _spy_connection_calls(monkeypatch):
    calls: list[str] = []
    from django import db as django_db

    import apps.telemetry.handlers as handlers_mod  # the module under test

    real_close_old = django_db.close_old_connections
    monkeypatch.setattr(
        django_db, "close_old_connections",
        lambda: (calls.append("close_old_connections"), real_close_old())[1],
    )
    monkeypatch.setattr(
        type(django_db.connection), "close",
        lambda self: calls.append("connection.close"),
        raising=False,
    )
    assert handlers_mod  # imported for clarity: _write does `from django.db import …`
    return calls


def test_sync_flush_never_touches_the_callers_connection(sync_handler, monkeypatch):
    """The contract: manage_connection=False on the flush()/caller path —
    no close_old_connections, and no connection.close even when the write
    fails and retries."""
    calls = _spy_connection_calls(monkeypatch)

    # Healthy write.
    sync_handler.emit(_record("fine"))
    sync_handler.flush()
    assert LogRecord.objects.filter(message="fine").exists()
    assert calls == []

    # Failing write: retries must not close the borrowed connection.
    monkeypatch.setattr(
        LogRecord.objects, "bulk_create",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db exploded")),
    )
    monkeypatch.setattr("time.sleep", lambda s: None)  # skip the backoff
    sync_handler.emit(_record("doomed"))
    sync_handler.flush()
    assert "connection.close" not in calls
    assert "close_old_connections" not in calls
    assert sync_handler.dropped >= 1  # still accounted for


def test_worker_path_still_manages_its_own_connection(monkeypatch):
    """The worker thread OWNS its thread-local connection: the manage
    branch stays on for it (direct _write call — the default)."""
    handler = DatabaseLogHandler(level="WARNING", start_worker=False)
    try:
        calls = _spy_connection_calls(monkeypatch)
        handler._write([handler._to_row(_record("worker-owned"))])
        assert "close_old_connections" in calls  # default manage_connection=True
    finally:
        handler.close()


def test_failed_sync_flush_does_not_poison_the_transaction(sync_handler, monkeypatch):
    """The atomic() wrap: after a failed flush inside the test's transaction,
    the SAME transaction keeps accepting statements. On Postgres, without
    the savepoint, the next query raises "current transaction is aborted";
    SQLite passes either way — run under TEST_DB=postgres for the real
    assertion."""
    monkeypatch.setattr(
        LogRecord.objects, "bulk_create",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db exploded")),
    )
    monkeypatch.setattr("time.sleep", lambda s: None)
    sync_handler.emit(_record("doomed"))
    sync_handler.flush()

    assert LogRecord.objects.count() == 0  # the transaction still answers queries
