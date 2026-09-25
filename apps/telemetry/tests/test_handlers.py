"""DatabaseLogHandler: record mapping and the four guards it exists for.

Handlers are built with ``start_worker=False`` so writes happen on the test's
own thread — a background writer opens its own database connection and cannot
see the test transaction.

The test settings disable LOGGING entirely, so nothing here is affected by (or
affects) the handler a real deployment installs.
"""

import logging

import pytest

from apps.smallstack.logging import (
    RequestContextFilter,
    bind_request_id,
    bind_trace_id,
    reset_request_id,
    reset_trace_id,
)
from apps.telemetry.handlers import DatabaseLogHandler, _guard
from apps.telemetry.models import LogRecord

pytestmark = pytest.mark.django_db


@pytest.fixture
def handler():
    h = DatabaseLogHandler(level="DEBUG", start_worker=False)
    yield h
    h.close()


def make_record(msg="hello", args=(), *, name="apps.tickets.views", level=logging.WARNING, exc_info=None, **extra):
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="/app/apps/tickets/views.py",
        lineno=42,
        msg=msg,
        args=args,
        exc_info=exc_info,
        func="close_ticket",
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _exc_info():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        return sys.exc_info()


# ---------------------------------------------------------------------------
# Record -> row
# ---------------------------------------------------------------------------


def test_emit_then_flush_writes_a_row(handler):
    handler.emit(make_record("Ticket 42 closed"))
    assert LogRecord.objects.count() == 0, "nothing is written until flush"

    handler.flush()

    row = LogRecord.objects.get()
    assert row.message == "Ticket 42 closed"
    assert row.level == "WARNING"
    assert row.level_no == logging.WARNING
    assert row.logger == "apps.tickets.views"
    assert row.func == "close_ticket"
    assert row.line == 42


def test_message_args_are_interpolated(handler):
    handler.emit(make_record("Ticket %s closed by %s", (42, "admin")))
    handler.flush()
    assert LogRecord.objects.get().message == "Ticket 42 closed by admin"


def test_exception_is_split_into_type_and_traceback(handler):
    handler.emit(make_record("failed", level=logging.ERROR, exc_info=_exc_info()))
    handler.flush()

    row = LogRecord.objects.get()
    assert row.exc_type == "ValueError"
    assert "Traceback (most recent call last)" in row.exc_text
    assert "ValueError: boom" in row.exc_text


def test_extra_fields_are_stored(handler):
    handler.emit(make_record("blocked", user_agent="curl/8.1", score=0.93))
    handler.flush()
    assert LogRecord.objects.get().extra == {"user_agent": "curl/8.1", "score": 0.93}


def test_unserializable_extra_does_not_lose_the_row(handler):
    """A JSONField write must not fail because a call site passed an object."""
    handler.emit(make_record("odd", thing=object()))
    handler.flush()

    row = LogRecord.objects.get()
    assert "object object at" in row.extra["thing"]


def test_extra_field_whose_repr_raises_does_not_drop_the_row(handler):
    """Regression: json_default() degrading a raising __repr__() to a
    placeholder (rather than re-raising) means the whole row survives with
    the poisoned field replaced — not the entire line vanishing."""

    class BadRepr:
        def __repr__(self):
            raise ValueError("nope")

    handler.emit(make_record("the important line", bad=BadRepr()))
    handler.flush()

    assert handler.errors == 0
    row = LogRecord.objects.get()
    assert row.message == "the important line"
    assert "repr() raised" in row.extra["bad"]


def test_extra_field_with_a_recursive_repr_does_not_drop_the_row(handler):
    class RecursiveRepr:
        def __repr__(self):
            return repr(self)

    handler.emit(make_record("still here", recursive=RecursiveRepr()))
    handler.flush()

    assert handler.errors == 0
    row = LogRecord.objects.get()
    assert row.message == "still here"
    assert "repr() raised" in row.extra["recursive"]


def test_control_lines_around_a_poisoned_extra_are_unaffected(handler):
    """The exact repro from the finding: a bad line sandwiched between two
    good ones must not take either neighbour down with it."""

    class BadRepr:
        def __repr__(self):
            raise ValueError("nope")

    handler.emit(make_record("control line before"))
    handler.emit(make_record("the important line", bad=BadRepr()))
    handler.emit(make_record("control line after"))
    handler.flush()

    messages = list(LogRecord.objects.order_by("pk").values_list("message", flat=True))
    assert messages == ["control line before", "the important line", "control line after"]


def test_jsonable_outer_fallback_does_not_touch_the_value_again(monkeypatch):
    """Even if json_default() itself somehow still let something through
    (belt-and-suspenders for the truly unexpected), _jsonable()'s own
    fallback must build a fresh payload rather than calling repr() on the
    poisoned value a second time — that second call is the original bug."""
    from apps.telemetry.handlers import _jsonable

    class Explodes:
        def __repr__(self):
            raise ValueError("still nope")

    def _dumps_that_raises(*args, **kwargs):
        raise TypeError("simulated json.dumps failure")

    monkeypatch.setattr("apps.telemetry.handlers.json.dumps", _dumps_that_raises)

    result = _jsonable({"bad": Explodes()})
    assert result == {"unserializable": "<extra could not be rendered>"}


def test_unserializable_extra_uses_repr_not_str_for_a_datetime(handler):
    """Matches apps.smallstack.docs.logging-audit.md's documented contract:
    non-serializable extra values are rendered with repr(), not str() — str()
    would make a datetime indistinguishable from a plain string."""
    import datetime

    handler.emit(make_record("odd", when=datetime.datetime(2026, 8, 16, 12, 30, 5)))
    handler.flush()

    row = LogRecord.objects.get()
    assert row.extra["when"] == "datetime.datetime(2026, 8, 16, 12, 30, 5)"


def test_context_ids_are_captured(handler):
    request_token = bind_request_id("req_abc")
    trace_token = bind_trace_id("trace_xyz")
    try:
        record = make_record("in a request")
        RequestContextFilter().filter(record)
        handler.emit(record)
    finally:
        reset_request_id(request_token)
        reset_trace_id(trace_token)
    handler.flush()

    row = LogRecord.objects.get()
    assert row.request_id == "req_abc"
    assert row.trace_id == "trace_xyz"


def test_oversized_message_is_truncated_not_rejected(handler):
    handler.emit(make_record("x" * 50_000))
    handler.flush()
    assert len(LogRecord.objects.get().message) == 10_000


def test_long_logger_name_is_truncated_to_field_width(handler):
    handler.emit(make_record("deep", name="apps." + "sub." * 100 + "mod"))
    handler.flush()
    assert len(LogRecord.objects.get().logger) == 200


# ---------------------------------------------------------------------------
# Guard 1: recursion
# ---------------------------------------------------------------------------


def test_records_logged_inside_the_handler_are_ignored(handler):
    """The write→query→log→write cycle: a record arriving while the guard is
    set must be dropped, or the handler feeds itself forever."""
    _guard.active = True
    try:
        handler.emit(make_record("emitted from inside a write"))
    finally:
        _guard.active = False

    handler.flush()
    assert LogRecord.objects.count() == 0


@pytest.mark.parametrize("logger_name", ["django.db.backends", "django.db.backends.sqlite3", "apps.telemetry.handlers"])
def test_excluded_loggers_are_never_captured(handler, logger_name):
    handler.emit(make_record("SELECT 1", name=logger_name))
    handler.flush()
    assert LogRecord.objects.count() == 0


def test_neighbouring_logger_names_are_not_over_excluded(handler):
    """Exclusion is a prefix match — don't let it swallow unrelated apps."""
    handler.emit(make_record("kept", name="apps.telemetry_report"))
    handler.flush()
    assert LogRecord.objects.count() == 1


# ---------------------------------------------------------------------------
# Guard 2: never raises
# ---------------------------------------------------------------------------


def test_emit_survives_a_broken_call_site(handler):
    """logger.info("%d", "seven") raises inside getMessage()."""
    handler.emit(make_record("%d items", ("seven",)))
    handler.flush()
    assert "unformattable" in LogRecord.objects.get().message


def test_emit_survives_a_record_missing_standard_attributes(handler):
    class Broken:
        name = "apps.broken"
        levelno = logging.ERROR

        def __getattr__(self, item):
            raise RuntimeError(f"no {item}")

    handler.emit(Broken())  # must not raise
    assert handler.errors == 1


def test_write_failure_is_swallowed(handler, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(LogRecord.objects, "bulk_create", explode)
    handler.emit(make_record("doomed"))
    handler.flush()  # must not raise

    assert handler.errors > 0


def test_missing_table_drops_quietly_without_retrying(handler, monkeypatch):
    """During the first `migrate` the table genuinely isn't there. Retrying
    can't help, and the warnings would bury the migrate output."""
    calls = []

    def missing(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("no such table: telemetry_logrecord")

    monkeypatch.setattr(LogRecord.objects, "bulk_create", missing)
    handler.emit(make_record("early"))
    handler.flush()

    assert len(calls) == 1, "must not burn the retry budget on a missing table"
    assert handler.dropped == 1


def test_giving_up_after_retries_counts_the_rows_as_dropped(handler, monkeypatch):
    """After three failed attempts the batch is gone — ``dropped`` must say so,
    or capture_status reports ``dropped: 0`` while records vanish. (Audit D10b.)"""
    monkeypatch.setattr("apps.telemetry.handlers.time.sleep", lambda s: None)

    def locked(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(LogRecord.objects, "bulk_create", locked)
    handler.emit(make_record("a"))
    handler.emit(make_record("b"))
    handler.flush()

    assert handler.dropped == 2


# ---------------------------------------------------------------------------
# Guard 4: bounded queue
# ---------------------------------------------------------------------------


def test_queue_overflow_drops_and_counts(handler):
    small = DatabaseLogHandler(level="DEBUG", queue_size=3, start_worker=False)
    try:
        for i in range(10):
            small.emit(make_record(f"record {i}"))

        assert small.dropped == 7
        small.flush()
        assert LogRecord.objects.count() == 3, "the first three survive; the flood is shed"
    finally:
        small.close()


def test_stats_reports_queue_health(handler):
    handler.emit(make_record("one"))
    stats = handler.stats()

    assert stats["queued"] == 1
    assert stats["level"] == "DEBUG"
    assert stats["dropped"] == 0

    handler.flush()
    assert handler.stats()["written"] == 1


# ---------------------------------------------------------------------------
# Level gating
# ---------------------------------------------------------------------------


def test_handler_level_gates_what_reaches_the_database():
    """Exercised through a real Logger, which is what production does — the
    level filter lives in Logger.callHandlers, not in Handler.handle()."""
    handler = DatabaseLogHandler(level="WARNING", start_worker=False)
    logger = logging.getLogger("apps.leveltest")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        logger.debug("debug")
        logger.info("info")
        logger.warning("warning")
        logger.error("error")
        handler.flush()

        assert sorted(row.level for row in LogRecord.objects.all()) == ["ERROR", "WARNING"]
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_ensure_worker_runs_even_when_the_level_filter_drops_the_record():
    """Regression: a fresh process's first log line being below the handler's
    current level must not skip starting the writer/poller thread — that
    thread is what lets the process ever discover an already-open capture
    window (_poll_capture runs on it). Gating _ensure_worker() behind the
    level check meant a process whose early lines are all INFO/DEBUG while
    the handler is still at its WARNING baseline never started the thread,
    no matter how long a window had been open.

    Verified via call count on a stand-in, not a real thread (the rest of
    this suite avoids real threads — see the module docstring) — this pins
    *that emit() calls _ensure_worker() unconditionally*, independent of
    threading timing.
    """
    h = DatabaseLogHandler(level="WARNING", start_worker=False)
    calls = []
    h._ensure_worker = lambda: calls.append(1)
    try:
        h.emit(make_record("below threshold", level=logging.INFO))
    finally:
        h.close()

    assert calls, "_ensure_worker() must run even for a record the level filter goes on to drop"
    assert LogRecord.objects.count() == 0, "the record itself is still correctly filtered out"


def test_ensure_worker_starts_the_thread_while_still_inside_apps_populate(monkeypatch):
    """Regression, round 6 (second bug, found only by the end-to-end proof,
    not by any unit test): TelemetryConfig.ready() calls _ensure_worker()
    synchronously, but Django's Apps.populate() sets `apps.ready = True`
    only *after* every app's ready() has returned (registry.py, Phase 3) —
    so a guard written as `if not django_apps.ready: return` is always
    true while still inside any app's own ready(), including telemetry's.
    The first cut of this fix used exactly that guard and silently never
    started the thread: worker_alive stayed False forever, caught only by
    manually running a real `manage.py shell` process end to end, not by
    any pytest run (this suite's own django app registry is always fully
    populated by the time a test executes, so calling _ensure_worker() from
    a test never reproduces the mid-populate() ordering).

    What must actually gate the thread is `models_ready` (models are
    importable), which is already true by the time any app's ready() runs
    (Phase 2 completes before Phase 3 starts) — this test drives that
    exact scenario: models_ready True, ready False.
    """
    from django.apps import apps as django_apps

    h = DatabaseLogHandler(level="WARNING", start_worker=True)
    try:
        assert django_apps.models_ready is True, "sanity: the test registry is always past Phase 2"
        monkeypatch.setattr(django_apps, "ready", False)

        h._ensure_worker()

        assert h._thread is not None and h._thread.is_alive(), (
            "the writer thread must start once models are importable, "
            "even before every app's own ready() has finished running"
        )
    finally:
        h.close()


def test_ensure_worker_still_waits_for_models_ready(monkeypatch):
    """The other half of the same guard: it must still refuse to start
    before models are safely importable (e.g. a record logged mid
    django.setup(), before Phase 2 of Apps.populate() has run) — the
    models_ready check isn't just renamed, it still does its job."""
    from django.apps import apps as django_apps

    h = DatabaseLogHandler(level="WARNING", start_worker=True)
    try:
        monkeypatch.setattr(django_apps, "models_ready", False)

        h._ensure_worker()

        assert h._thread is None, "must not start a thread before models are importable"
    finally:
        h.close()


def test_ensure_worker_does_not_run_inside_the_recursion_guard():
    """The guard check must still short-circuit before anything else —
    including the now-unconditional _ensure_worker() call — or a record
    logged from inside the handler's own write path could restart machinery
    while guarded."""
    h = DatabaseLogHandler(level="DEBUG", start_worker=False)
    calls = []
    h._ensure_worker = lambda: calls.append(1)
    _guard.active = True
    try:
        h.emit(make_record("emitted from inside a write"))
    finally:
        _guard.active = False
        h.close()

    assert calls == []


def test_raising_the_handler_level_takes_effect_immediately():
    """What a capture window closing does: setLevel() must stop capture even
    for records a still-verbose logger keeps dispatching."""
    handler = DatabaseLogHandler(level="DEBUG", start_worker=False)
    logger = logging.getLogger("apps.leveltest2")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        logger.debug("during the window")
        handler.setLevel(logging.WARNING)
        logger.debug("after the window")
        handler.flush()

        assert [row.message for row in LogRecord.objects.all()] == ["during the window"]
    finally:
        logger.removeHandler(handler)
        handler.close()
