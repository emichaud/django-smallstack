"""A logging handler that persists records to the database.

Writing log lines to the same database the app serves from is a trap in four
specific ways. Each guard below exists because of one of them:

1. **Recursion.** Writing a row runs a query; the query logs through
   ``django.db.backends``; that record reaches this handler, which writes a
   row. A thread-local guard plus a logger-name exclusion breaks the cycle.
2. **Raising.** A handler that raises turns a log call into an application
   error — logging must never be the thing that breaks a request. Every path
   here swallows.
3. **Latency.** A synchronous ``INSERT`` on the request path taxes every
   logging call. Records go onto a bounded queue; a background thread batches
   them out.
4. **Unbounded growth under load.** An incident produces a flood of ERROR
   lines exactly when the database is least able to absorb them. The queue is
   bounded and drops on overflow, counting what it dropped rather than
   blocking the request that was trying to log.

Instances are built by ``dictConfig`` during ``django.setup()`` — before the
app registry is populated — so nothing here may import models at module scope.
The writer thread starts lazily on the first record, once the registry is ready.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

from apps.smallstack.logging import extract_extra, json_default, safe_message

from .logger_match import matches_prefix

# Loggers never captured to the database. django.db.backends would recurse
# (see guard 1); apps.telemetry is this subsystem reporting on itself.
#
# django.server is the *development* server's per-request access log. Excluded
# for three reasons: it does not exist in production (gunicorn/uvicorn write
# their own access logs, not through Django's logging), its content — method,
# path, status, size — is already stored properly by apps.activity's RequestLog
# with a user and a request_id attached, and capturing it makes any tail of
# this table mostly self-traffic. Anything polling the log — the viewer's live
# mode every 5s, or a client polling /api/logger/records/ — otherwise writes
# one INFO record per poll into the very table it is reading. Measured: 10
# polls of the logger API produced 11 new records, all django.server.
DEFAULT_EXCLUDE_LOGGERS = ("django.db.backends", "apps.telemetry", "django.server")

MAX_MESSAGE_CHARS = 10_000
MAX_EXC_CHARS = 20_000

# True for any thread currently inside this handler's own machinery. Anything
# logged while it is set is dropped rather than persisted — that is what stops
# the write→query→log→write cycle.
_guard = threading.local()

# Used only to render tracebacks when no formatter has done so yet.
_exc_formatter = logging.Formatter()

# Every live handler instance, so the CLI and (in Phase 2) the UI can report
# queue depth and drop counts without reaching into logging internals.
_instances: list[DatabaseLogHandler] = []

logger = logging.getLogger(__name__)


def get_handlers() -> list[DatabaseLogHandler]:
    """Return the installed database log handlers (usually one, or none)."""
    return list(_instances)


def _level_number(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).upper())
    return resolved if isinstance(resolved, int) else logging.WARNING


def _is_excluded(logger_name: str, excluded: tuple[str, ...]) -> bool:
    """True when ``logger_name`` is an excluded logger or a child of one.

    Matching the logger hierarchy, not a raw string prefix: a plain
    ``startswith`` would also swallow ``apps.telemetry_report``, which is a
    different app that happens to share leading characters. See
    ``logger_match.matches_prefix`` — the log viewer's own logger filter
    (``views.py::LogListView.filtered_queryset``) reuses the same predicate so
    the two can't drift apart.
    """
    return any(matches_prefix(logger_name, prefix) for prefix in excluded)


def _is_missing_table(exc: Exception) -> bool:
    """True when the failure is "the table isn't there yet", not a transient error.

    Happens on a fresh database between ``django.setup()`` and the first
    ``migrate``. Matched on message text because the wording is backend-specific
    (SQLite says "no such table", Postgres "does not exist") and both arrive as
    a generic ``OperationalError`` / ``ProgrammingError``.
    """
    message = str(exc).lower()
    return "no such table" in message or ("relation" in message and "does not exist" in message)


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    """Coerce ``extra`` into something a JSONField will accept.

    ``default=json_default`` means an unserializable value becomes its
    (bounded) ``repr()`` instead of costing us the whole record — see
    ``apps.smallstack.logging.json_default`` for why ``repr()`` and not
    ``str()``. ``json_default`` is itself defensive against a ``__repr__``
    that raises, so in practice this outer ``except`` is a last-resort net,
    not the primary defense.

    That outer net must never re-touch ``value``: the original bug here was
    calling ``repr(value)`` on the very dict whose member's ``__repr__`` just
    raised inside ``json_default`` — which raises *again*, uncaught, and
    drops the whole record (not just the poisoned field). Build a fixed,
    self-contained string instead, the same shape ``JSONFormatter.format()``'s
    outer fallback already uses (build fresh, don't re-touch the poisoned
    value).
    """
    try:
        return json.loads(json.dumps(value, default=json_default))
    except Exception:  # pragma: no cover - defensive
        return {"unserializable": "<extra could not be rendered>"}


class DatabaseLogHandler(logging.Handler):
    """Buffer log records and write them to ``telemetry.LogRecord`` in batches.

    Tunables are passed from ``LOGGING`` in settings:

    ``queue_size``
        Bound on buffered records. Overflow increments ``dropped`` — visible in
        :meth:`stats` — rather than blocking the thread that logged.
    ``batch_size`` / ``flush_interval``
        How many records per ``bulk_create``, and how long the writer waits for
        a batch to fill before writing what it has.
    ``poll_interval``
        How often the writer re-reads the capture window. The check happens on
        the writer thread precisely so that ``emit()`` never touches the
        database.
    """

    def __init__(
        self,
        level: str | int = "WARNING",
        queue_size: int = 1000,
        batch_size: int = 200,
        flush_interval: float = 1.0,
        poll_interval: float = 5.0,
        shutdown_timeout: float = 3.0,
        exclude_loggers: tuple[str, ...] | list[str] | None = None,
        start_worker: bool = True,
    ) -> None:
        super().__init__(level=_level_number(level))
        self.queue_size = queue_size
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.poll_interval = poll_interval
        self.shutdown_timeout = shutdown_timeout
        self._exclude = tuple(exclude_loggers or DEFAULT_EXCLUDE_LOGGERS)
        # False keeps everything on the calling thread: records stay queued
        # until someone calls flush(). Used by the tests — a writer thread has
        # its own database connection and so cannot see the open test
        # transaction — and available to anyone running somewhere a background
        # thread is unwelcome. Nothing is written until flush() is called.
        self.start_worker = start_worker

        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._stopping = threading.Event()

        self.dropped = 0
        self.written = 0
        self.errors = 0
        self._last_poll = 0.0
        self._no_table_until = 0.0

        _instances.append(self)

    # -- the logging.Handler contract ------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Queue a record. Never raises, never touches the database."""
        try:
            if getattr(_guard, "active", False):
                return

            # Belt-and-suspenders start of the writer/poller thread. The
            # primary start point is now TelemetryConfig.ready() (see
            # apps.py), which starts it eagerly for every process — that's
            # what actually satisfies "a fresh process picks up an
            # already-open capture window within one poll interval", since
            # this call site is gated by the same level check as everything
            # else in emit() and so cannot help a below-baseline record.
            # This call still matters for one case ready() can't cover: a
            # gunicorn deployment with preload_app = True forks workers
            # *after* the app (and this handler) is already loaded in the
            # master, so the thread ready() started there does not survive
            # into the forked workers. Calling _ensure_worker() here starts
            # it in each worker on that worker's first record instead —
            # still no-ops until django_apps.models_ready, so it doesn't
            # touch the database or spin up a thread at dictConfig/import
            # time.
            self._ensure_worker()

            # Logger.callHandlers already applies this, but checking here too
            # makes the handler correct however it is driven — including the
            # capture window, which changes self.level out from under it.
            if record.levelno < self.level:
                return
            if _is_excluded(record.name, self._exclude):
                return

            row = self._to_row(record)
            try:
                self._queue.put_nowait(row)
            except queue.Full:
                self.dropped += 1
                return
        except Exception:  # pragma: no cover - defensive
            self.errors += 1

    def flush(self) -> None:
        """Write everything currently queued, synchronously.

        Called by ``logging.shutdown()`` at interpreter exit, and by tests that
        want the queue settled before asserting on rows.
        """
        deadline = time.monotonic() + self.shutdown_timeout
        while time.monotonic() < deadline:
            batch = self._take_batch()
            if not batch:
                return
            self._write_guarded(batch)

    def close(self) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.shutdown_timeout)
        try:
            self.flush()
        finally:
            if self in _instances:
                _instances.remove(self)
            super().close()

    # -- introspection ---------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Queue health, for the CLI and the Phase 2 UI.

        ``dropped`` above zero means the queue overflowed — the app logged
        faster than the database absorbed it. Raise ``queue_size``, or raise
        the capture level so less is queued in the first place.
        """
        return {
            "level": logging.getLevelName(self.level),
            "queued": self._queue.qsize(),
            "queue_size": self.queue_size,
            "written": self.written,
            "dropped": self.dropped,
            "errors": self.errors,
            "worker_alive": bool(self._thread and self._thread.is_alive()),
        }

    # -- record → row ----------------------------------------------------

    def _to_row(self, record: logging.LogRecord) -> dict[str, Any]:
        exc_type = ""
        exc_text = ""
        if record.exc_info and record.exc_info[0] is not None:
            exc_type = record.exc_info[0].__name__
            if not record.exc_text:
                # Cache it on the record so sibling handlers don't re-render.
                record.exc_text = _exc_formatter.formatException(record.exc_info)
            exc_text = record.exc_text or ""
        elif record.exc_text:
            exc_text = record.exc_text

        return {
            "ts": datetime.fromtimestamp(record.created, tz=dt_timezone.utc),
            "level": record.levelname[:10],
            "level_no": max(0, min(record.levelno, 32767)),
            "logger": record.name[:200],
            "message": safe_message(record)[:MAX_MESSAGE_CHARS],
            "module": (record.module or "")[:200],
            "func": (record.funcName or "")[:200],
            "line": max(0, record.lineno or 0),
            "request_id": str(getattr(record, "request_id", "") or "")[:255],
            "trace_id": str(getattr(record, "trace_id", "") or "")[:255],
            "exc_type": exc_type[:200],
            "exc_text": exc_text[:MAX_EXC_CHARS],
            "extra": _jsonable(extract_extra(record)),
        }

    # -- writer thread ---------------------------------------------------

    def _ensure_worker(self) -> None:
        if not self.start_worker:
            return
        if self._thread is not None and self._thread.is_alive():
            return

        # Records logged during django.setup() arrive before models are usable.
        # Leave them queued; a later record starts the worker and they flush then.
        #
        # Gate on models_ready, not the coarser ready flag. Apps.populate()
        # sets ready = True only *after* every app's AppConfig.ready() has
        # returned (see django.apps.registry.Apps.populate: Phase 3 runs
        # ready() for each app, then sets self.ready = True once the whole
        # loop is done) — so a check against `ready` is never true while
        # still inside any app's own ready(), including this handler's own
        # TelemetryConfig.ready() -> _start_log_writers() call in apps.py,
        # which would otherwise silently no-op every time (this was caught
        # by the two-process end-to-end proof, not by a unit test — the
        # thread never started, worker_alive stayed False). models_ready is
        # what actually matters here: it flips at the end of Phase 2, before
        # any app's ready() runs, and is exactly "model imports (LogRecord,
        # LogCaptureWindow) are safe" — the thing this guard exists to wait
        # for in the first place.
        from django.apps import apps as django_apps

        if not django_apps.models_ready:
            return

        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="smallstack-log-writer",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        # Guard the whole thread, not each write: every query, connection reset
        # and error report this thread produces is "inside the handler" and must
        # not come back around as a new record to persist. It still reaches the
        # console handler, so failures here stay visible.
        _guard.active = True
        try:
            while not self._stopping.is_set():
                batch = self._take_batch(block_for=self.flush_interval)
                if batch:
                    self._write(batch)
                self._poll_capture()
        finally:
            _guard.active = False

    def _take_batch(self, block_for: float | None = None) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        if block_for:
            try:
                batch.append(self._queue.get(timeout=block_for))
            except queue.Empty:
                return batch
        while len(batch) < self.batch_size:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def _write_guarded(self, rows: list[dict[str, Any]]) -> None:
        """Write with the recursion guard set — for callers off the worker thread."""
        previous = getattr(_guard, "active", False)
        _guard.active = True
        try:
            self._write(rows)
        finally:
            _guard.active = previous

    def _write(self, rows: list[dict[str, Any]]) -> None:
        from django.db import close_old_connections, connection

        from .models import LogRecord

        # The table genuinely doesn't exist yet during the first `migrate`.
        # Retrying can't help and the warnings would bury the migrate output.
        if time.monotonic() < self._no_table_until:
            self.dropped += len(rows)
            return

        for attempt in range(3):
            try:
                close_old_connections()
                LogRecord.objects.bulk_create([LogRecord(**row) for row in rows])
                self.written += len(rows)
                return
            except Exception as exc:
                self.errors += 1
                if _is_missing_table(exc):
                    self._no_table_until = time.monotonic() + 60.0
                    self.dropped += len(rows)
                    logger.debug("telemetry_logrecord not present yet; dropping %d record(s)", len(rows))
                    return
                # "database is locked" (SQLite) and dropped connections both
                # recover on retry; force a fresh connection and back off.
                try:
                    connection.close()
                except Exception:
                    pass
                if attempt == 2:
                    self.dropped += len(rows)  # was only logged, never counted (audit D10b)
                    logger.warning("Dropped %d log record(s) after repeated write failures", len(rows), exc_info=True)
                    return
                time.sleep(0.1 * (3**attempt))

    def _poll_capture(self) -> None:
        """Re-read the capture window and apply it to this process."""
        now = time.monotonic()
        if now - self._last_poll < self.poll_interval:
            return
        self._last_poll = now

        try:
            from . import capture

            level_no = capture.effective_level(capture.active_window())
            if level_no != self.level:
                self.setLevel(level_no)
            capture.apply_levels(level_no)
        except Exception:
            self.errors += 1
