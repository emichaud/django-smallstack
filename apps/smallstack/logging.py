"""Structured JSON logging and request-scoped log context.

Two pieces, wired together in ``config/settings/*``:

``RequestContextFilter``
    Injects the current request ID (and trace ID, when one is bound) onto
    every :class:`logging.LogRecord` that reaches a handler. Attach it to
    *handlers*, not loggers — a handler filter sees records propagated up
    from child loggers, a logger filter does not.

``JSONFormatter`` / ``TextFormatter``
    Render a record for production (one JSON object per line) or for a
    development console (human-readable, with the request ID appended when
    there is one).

The context itself lives in :mod:`contextvars`, so it is correct under
threaded WSGI, ASGI, and background tasks without any thread-local
bookkeeping at the call sites. ``RequestIDMiddleware`` binds the request ID;
:func:`bind_trace_id` is the seam for multi-step work (agent runs, pipelines)
that wants every log line it emits stitched to one trace.

**Nothing here may import Django.** ``dictConfig`` runs during
``django.setup()``, before the app registry is populated, so this module is
imported earlier than models or settings can safely be touched.

Why not a ``%``-style format string with ``"message": "%(message)s"``? Because
it produces invalid JSON the moment a message contains a quote, a backslash, or
a newline — and every ``logger.exception()`` call appends a multi-line
traceback *after* the closing brace. It also silently discards ``extra={...}``
fields. Formatting through :func:`json.dumps` fixes all three.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from typing import Any

__all__ = [
    "JSONFormatter",
    "TextFormatter",
    "RequestContextFilter",
    "bind_request_id",
    "bind_trace_id",
    "extract_extra",
    "get_request_id",
    "get_trace_id",
    "json_default",
    "safe_message",
]

# Cap on the rendered form of a value that json.dumps() can't encode natively
# (see json_default below). Without a bound, one hostile object's repr() could
# dwarf everything else in the record.
MAX_UNSERIALIZABLE_REPR_CHARS = 2000


def json_default(value: Any) -> str:
    """Render a value ``json.dumps`` can't encode natively, for its ``default=`` hook.

    ``repr()`` rather than ``str()``: for a ``datetime``, that's the difference
    between ``'2026-08-16 12:00:00'`` (indistinguishable from a plain string
    once it's in a JSON field) and ``'datetime.datetime(2026, 8, 16, 12, 0, 0)'``
    (unambiguous — tells you it was never a string to begin with). Truncated so
    a single oversized object can't blow up a log line or a database row.

    ``repr(value)`` itself can raise — any ``__repr__`` that does real work
    (formats internal state, walks a data structure) can fail, and a
    hand-written recursive ``__repr__`` raises ``RecursionError``. Guarded here
    so one poisoned value in ``extra`` degrades to a placeholder for *that
    field only*, instead of raising back out of ``json.dumps`` and costing the
    caller the whole payload.
    """
    try:
        text = repr(value)
    except Exception as exc:  # pragma: no cover - defensive
        return f"<{type(value).__name__} repr() raised: {exc!r}>"
    if len(text) > MAX_UNSERIALIZABLE_REPR_CHARS:
        text = text[:MAX_UNSERIALIZABLE_REPR_CHARS] + "...(truncated)"
    return text


# ---------------------------------------------------------------------------
# Request-scoped context
# ---------------------------------------------------------------------------

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("smallstack_request_id", default="")
_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("smallstack_trace_id", default="")


def bind_request_id(request_id: str) -> contextvars.Token[str]:
    """Bind the request ID for the current context.

    Returns the token the caller MUST pass to ``_request_id.reset()`` in a
    ``finally`` block — WSGI worker threads are reused, and an unreset value
    would leak into the next request handled by that thread.
    """
    return _request_id.set(request_id or "")


def bind_trace_id(trace_id: str) -> contextvars.Token[str]:
    """Bind a trace ID so every log line from this unit of work shares it.

    Use around any multi-step operation whose log lines you want to read back
    as one story — a scheduled job, a webhook delivery chain, an agent run::

        token = bind_trace_id(f"trace_{uuid.uuid4().hex}")
        try:
            ...
        finally:
            reset_trace_id(token)

    Returns the reset token, same contract as :func:`bind_request_id`.
    """
    return _trace_id.set(trace_id or "")


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Restore the request ID bound before ``token`` was issued."""
    _request_id.reset(token)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """Restore the trace ID bound before ``token`` was issued."""
    _trace_id.reset(token)


def get_request_id() -> str:
    """Return the request ID bound to the current context, or ``""``."""
    return _request_id.get()


def get_trace_id() -> str:
    """Return the trace ID bound to the current context, or ``""``."""
    return _trace_id.get()


class RequestContextFilter(logging.Filter):
    """Copy the bound request/trace IDs onto each record.

    Always returns ``True`` — this filter enriches records, it never drops
    them. Attach it to a handler so it also sees records that propagated up
    from child loggers.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Don't clobber an explicit extra={"request_id": ...} from a call site.
        if not getattr(record, "request_id", ""):
            # The contextvar is empty for Django's own auto-logged 4xx/5xx access
            # lines: BaseHandler.get_response() calls log_response(...,
            # request=request) *after* _middleware_chain(request) returns, i.e.
            # after RequestIDMiddleware's `finally: reset_request_id(token)` has
            # already fired. log_response's `request=request` kwarg lands on
            # record.request, though — untouched by the contextvar reset — so
            # fall back to reading the ID back off it.
            record.request_id = _request_id.get() or self._request_id_from_record(record)
        if not getattr(record, "trace_id", ""):
            record.trace_id = _trace_id.get()
        return True

    @staticmethod
    def _request_id_from_record(record: logging.LogRecord) -> str:
        """Best-effort fallback: read ``.id`` off ``record.request``.

        Defensive at every step — ``record.request`` may be absent (most
        records never carry one), may not actually be an ``HttpRequest`` (a
        call site could pass anything via ``extra={"request": ...}``), and
        its ``.id`` may not be a string. A logging filter must never raise:
        that would drop the very record it's trying to enrich.
        """
        try:
            request = getattr(record, "request", None)
            if request is None:
                return ""
            request_id = getattr(request, "id", "")
            return request_id if isinstance(request_id, str) else ""
        except Exception:  # pragma: no cover - defensive, filter must never raise
            return ""


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

# Attributes the logging module itself puts on every record. Anything on a
# record that is NOT in this set (and not one of ours) arrived via
# ``extra={...}`` at the call site and belongs in the output.
_STANDARD_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# Attributes RequestContextFilter adds — promoted to top-level fields, so they
# must not be swept up again as "extra".
_CONTEXT_ATTRS = frozenset({"request_id", "trace_id"})


def safe_message(record: logging.LogRecord) -> str:
    """Interpolate the record's message, surviving a bad call site.

    ``logger.info("%d items", "seven")`` raises inside ``getMessage()``. A
    formatter that propagates that loses the log line entirely — and the line
    is usually the clue you need. Degrade to the raw template plus the args.
    """
    try:
        return record.getMessage()
    except Exception as exc:  # pragma: no cover - defensive
        return f"<unformattable log message: {exc!r} msg={record.msg!r} args={record.args!r}>"


def extract_extra(record: logging.LogRecord) -> dict[str, Any]:
    """Return the ``extra={...}`` fields a call site attached to ``record``.

    Anything on the record that isn't a logging built-in and isn't one of the
    IDs :class:`RequestContextFilter` injects arrived via ``extra``. Private
    attributes (``_foo``) are treated as internal bookkeeping and skipped.
    """
    return {
        key: _redact_request(value)
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS and key not in _CONTEXT_ATTRS and not key.startswith("_")
    }


def _redact_request(value: Any) -> Any:
    """Reduce an ``HttpRequest`` in ``extra`` to its method and path.

    Django's ``log_response`` attaches the request object to every
    ``django.request`` record, and its ``repr()`` carries the full query
    string — so a feed URL's ``?token=<raw key>`` was written verbatim into
    JSON log lines and the ``LogRecord.extra`` column on any 4xx/5xx. The path
    is what's useful for debugging; the query is where credentials ride.
    (Audit 2026-09-13, C3.) Duck-typed so this module never imports Django's
    HTTP machinery.
    """
    if hasattr(value, "method") and hasattr(value, "path") and hasattr(value, "GET"):
        try:
            return f"<{type(value).__name__}: {value.method} {value.path!r}>"
        except Exception:  # pragma: no cover - defensive
            return f"<{type(value).__name__}>"
    return value


class JSONFormatter(logging.Formatter):
    """Render each record as a single valid JSON object on one line.

    Emits ``time``, ``level``, ``name``, ``module``, ``func``, ``line`` and
    ``message`` always; ``request_id`` / ``trace_id`` when bound; ``exc_type``
    and ``exc`` when the record carries an exception; ``stack`` for
    ``stack_info=True``; and an ``extra`` object holding any ``extra={...}``
    fields from the call site.

    Timestamps are ISO-8601 in UTC (``2026-08-16T14:23:01.123Z``) regardless of
    the container's timezone, so lines from different hosts sort correctly.

    ``ensure_ascii`` defaults to ``True`` so output is pure ASCII and can never
    raise ``UnicodeEncodeError`` on a stream with a non-UTF-8 encoding. JSON
    parsers decode the ``\\uXXXX`` escapes back to the original text, so
    collectors see the real string. Pass ``ensure_ascii=False`` if you read raw
    container logs by eye and know the stream is UTF-8.
    """

    def __init__(self, *, datefmt: str | None = None, ensure_ascii: bool = True) -> None:
        super().__init__(datefmt=datefmt)
        self.ensure_ascii = ensure_ascii

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Render the record's timestamp as ISO-8601 in UTC.

        Overridden rather than setting ``Formatter.converter``: this is
        explicit about the format, and it always resolves against UTC, so the
        container's timezone can't change the output.
        """
        utc = time.gmtime(record.created)
        if datefmt:
            return time.strftime(datefmt, utc)
        return f"{time.strftime('%Y-%m-%dT%H:%M:%S', utc)}.{int(record.msecs):03d}Z"

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "message": safe_message(record),
        }

        for key in ("request_id", "trace_id"):
            value = getattr(record, key, "")
            if value:
                payload[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            # Reuse the cached text when another handler already rendered it;
            # formatException() is not cheap and every handler sees the record.
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            payload["exc"] = record.exc_text
        elif record.exc_text:
            payload["exc"] = record.exc_text

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        extra = extract_extra(record)
        if extra:
            payload["extra"] = extra

        try:
            return json.dumps(payload, default=json_default, ensure_ascii=self.ensure_ascii)
        except Exception as exc:  # pragma: no cover - defensive
            # A log formatter must never raise: a handler exception here would
            # be swallowed by logging and the line lost. Fall back to a minimal
            # object that is guaranteed serializable.
            return json.dumps(
                {
                    "time": payload["time"],
                    "level": record.levelname,
                    "name": record.name,
                    "message": payload["message"],
                    "log_format_error": repr(exc),
                },
                default=str,
            )


class TextFormatter(logging.Formatter):
    """Human-readable console output that carries the request ID.

    Renders like the stdlib formatter, then appends ``request_id=...`` /
    ``trace_id=...`` at the end of the line when they are bound. Putting them
    last keeps the left edge scannable while still letting you correlate a
    console line to an ``X-Request-ID`` from the browser's network tab.
    """

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        suffix = " ".join(
            f"{key}={getattr(record, key)}" for key in ("request_id", "trace_id") if getattr(record, key, "")
        )
        return f"{line} {suffix}" if suffix else line
