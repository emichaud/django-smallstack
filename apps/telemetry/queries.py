"""Transport-agnostic telemetry queries — the one implementation.

Three surfaces read and control log capture: the REST API (``api.py``), the MCP
tools (``mcp_tools.py``), and the CLI (``management/commands/``). They must
agree on what ``level=WARNING`` means, on what counts as a valid duration, and
on what a record looks like once serialized. The only reliable way to get that
is for there to be one implementation and three thin adapters.

This module is that implementation. It knows nothing about HTTP, MCP, or
argparse: inputs are plain values, output is JSON-safe dicts, and invalid input
raises :class:`TelemetryQueryError` for the adapter to render however its
transport renders errors.

The rule is not theoretical. Two of this feature's findings were one predicate
implemented twice and drifting: the viewer's ``?logger=`` filter was a raw
``startswith`` while the handler's exclusion check was hierarchy-aware, and the
JSON formatter's ``repr()`` contract disagreed with the DB handler's. Both were
"the same rule, written twice."

Filter semantics deliberately match the staff viewer (``views.py``), which
composes its own queryset for template rendering but shares the underlying
predicates (``logger_match.prefix_q``, level-and-above, message-plus-traceback
search).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import capture
from .logger_match import prefix_q
from .models import LogRecord

# Ordered low to high. "This level and above" is how operators think — asking
# for WARNING means you want ERROR too.
LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Truncation applies to *list* results only; ``get_record`` is untruncated,
# which is what it is for. One traceback can be 20 KB, and fifty inlined would
# fill a caller's context (or an agent's) for no benefit.
LIST_MESSAGE_CHARS = 2000
LIST_EXC_CHARS = 500

FILTER_NAMES = (
    "level",
    "logger",
    "request_id",
    "trace_id",
    "search",
    "since",
    "until",
    "after_id",
    "limit",
)


class TelemetryQueryError(ValueError):
    """Invalid input. Adapters render this as a 400 / tool error / CLI error."""


# --- parsing ---------------------------------------------------------------


def parse_level(value: Any) -> str:
    level = str(value or "").strip().upper()
    if not level:
        return ""
    if level not in LEVELS:
        raise TelemetryQueryError(f"level must be one of {', '.join(LEVELS)}, got {level!r}")
    return level


def parse_capture_level(value: Any) -> str:
    """A capture-window level: known, and strictly below the baseline.

    A window at or above the baseline captures nothing the baseline doesn't
    already (``effective_level`` takes the min) — accepting one would audit,
    log, and report "capturing" while changing nothing. (Audit 2026-09-13, D6.)
    """
    level = parse_level(value) or "DEBUG"
    baseline = capture.baseline_level()
    if LEVELS[level] >= baseline:
        raise TelemetryQueryError(
            f"level {level} would capture nothing extra — the baseline already records "
            f"{logging.getLevelName(baseline)} and above; choose a lower level"
        )
    return level


def parse_timestamp(value: Any, field: str) -> datetime | None:
    """Absolute ISO-8601 only.

    No "15m" shorthand: the viewer offers relative ranges because a human picks
    from a dropdown, but a programmatic caller has a clock, and a relative
    window shifts underneath a paginated loop as time passes mid-iteration.
    """
    if value in (None, ""):
        return None
    parsed: datetime | None = value if isinstance(value, datetime) else parse_datetime(str(value))
    if parsed is None:
        raise TelemetryQueryError(
            f"{field} must be an ISO-8601 datetime (e.g. 2026-08-17T01:30:00Z), got {value!r}"
        )
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def parse_int(value: Any, field: str, *, minimum: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise TelemetryQueryError(f"{field} must be an integer, got {value!r}") from None
    if parsed < minimum:
        raise TelemetryQueryError(f"{field} must be >= {minimum}, got {parsed}")
    if maximum is not None and parsed > maximum:
        raise TelemetryQueryError(f"{field} must be <= {maximum}, got {parsed}")
    return parsed


def reject_unknown(supplied, allowed, kind: str = "query parameter") -> None:
    """Raise on anything we don't implement.

    The single most important rule on these surfaces, and the only one that
    makes them *harder* to use — which is why it is enforced centrally rather
    than left to each adapter to remember. Silently ignoring ``sevrity=ERROR``
    hands back the whole unfiltered table and calls it success; a human
    eventually notices, an automated caller reasons confidently from it.
    """
    unknown = sorted(set(supplied) - set(allowed))
    if unknown:
        raise TelemetryQueryError(
            f"Unknown {kind}{'s' if len(unknown) > 1 else ''}: "
            f"{', '.join(repr(u) for u in unknown)}. Valid: {', '.join(sorted(allowed))}"
        )


# --- serialization ---------------------------------------------------------


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit], True)


def serialize_record(record: LogRecord, *, full: bool) -> dict:
    message, message_truncated = (
        (record.message, False) if full else _truncate(record.message, LIST_MESSAGE_CHARS)
    )
    exc_text, exc_truncated = (
        (record.exc_text, False) if full else _truncate(record.exc_text, LIST_EXC_CHARS)
    )
    data = {
        "id": record.pk,
        "ts": record.ts.isoformat(),
        "level": record.level,
        "level_no": record.level_no,
        "logger": record.logger,
        "message": message,
        "message_truncated": message_truncated,
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "exc_type": record.exc_type,
        "exc_text": exc_text,
        "exc_truncated": exc_truncated,
        "extra": record.extra or {},
        "url": f"/api/logger/records/{record.pk}/",
    }
    if full:
        data.update({"module": record.module, "func": record.func, "line": record.line})
    return data


# --- reads -----------------------------------------------------------------


def search_records(
    *,
    level: Any = "",
    logger: Any = "",
    request_id: Any = "",
    trace_id: Any = "",
    search: Any = "",
    since: Any = None,
    until: Any = None,
    after_id: Any = None,
    limit: Any = None,
) -> dict:
    """Filtered log records, newest-first — or oldest-first when tailing.

    ``after_id`` is the cursor: records strictly newer than that id, returned
    oldest-first so ``next_after_id`` advances monotonically. Page numbers are
    wrong for a live tail, because new rows arrive at the top and shift every
    page down, so page 2 re-reads what page 1 already returned.
    """
    applied: dict[str, Any] = {}
    qs = LogRecord.objects.all()

    level = parse_level(level)
    if level:
        qs = qs.filter(level_no__gte=LEVELS[level])
        applied["level"] = level

    logger_prefix = str(logger or "").strip()
    if logger_prefix:
        # Hierarchy-aware: `apps.telemetry` includes `apps.telemetry.handlers`
        # but not `apps.telemetry_report`. Same predicate the capture handler's
        # own exclusion list uses.
        qs = qs.filter(prefix_q("logger", logger_prefix))
        applied["logger"] = logger_prefix

    for field, value in (("request_id", request_id), ("trace_id", trace_id)):
        text = str(value or "").strip()
        if text:
            qs = qs.filter(**{field: text})
            applied[field] = text

    search_text = str(search or "").strip()
    if search_text:
        # Tracebacks are searched too: the exception class is what you remember,
        # and it lives in exc_text rather than the message.
        qs = qs.filter(Q(message__icontains=search_text) | Q(exc_text__icontains=search_text))
        applied["search"] = search_text

    since_dt = parse_timestamp(since, "since")
    if since_dt:
        qs = qs.filter(ts__gte=since_dt)
        applied["since"] = since_dt.isoformat()

    until_dt = parse_timestamp(until, "until")
    if until_dt:
        qs = qs.filter(ts__lte=until_dt)
        applied["until"] = until_dt.isoformat()

    cursor = None
    if after_id not in (None, ""):
        cursor = parse_int(after_id, "after_id", minimum=0)
        qs = qs.filter(pk__gt=cursor)
        applied["after_id"] = cursor

    resolved_limit = (
        DEFAULT_LIMIT if limit in (None, "") else parse_int(limit, "limit", minimum=1, maximum=MAX_LIMIT)
    )
    applied["limit"] = resolved_limit

    total = qs.count()
    # Cursor mode pages on the cursor's own axis. Records are written in
    # batches, so insertion order is not capture order (see prune_logs): a
    # record captured earlier can land at a higher pk. Ordering a pk cursor by
    # ts would advance next_after_id past rows the page never returned.
    ordering = ("pk",) if cursor is not None else ("-ts", "-pk")

    # One extra row is the cheapest correct has_more: no second COUNT, and no
    # "was the last page exactly `limit` long?" ambiguity.
    rows = list(qs.order_by(*ordering)[: resolved_limit + 1])
    has_more = len(rows) > resolved_limit
    rows = rows[:resolved_limit]

    return {
        "records": [serialize_record(r, full=False) for r in rows],
        "count": len(rows),
        "has_more": has_more,
        "next_after_id": rows[-1].pk if rows else cursor,
        "total_matching": total,
        "applied_filters": applied,
    }


def get_record(record_id: Any) -> dict | None:
    """One record with the full untruncated traceback, or None."""
    pk = parse_int(record_id, "id", minimum=1)
    record = LogRecord.objects.filter(pk=pk).first()
    return serialize_record(record, full=True) if record else None


def logger_counts(limit: Any = 100) -> dict:
    """Logger names that have produced records, most active first.

    Discovery: a caller filtering by logger has to know which names exist.
    Guessing ``apps.inventory`` when the app logs under
    ``apps.inventory.services`` returns nothing, and "no such logger" is
    indistinguishable from "no matching records" unless you can list them.
    """
    resolved = parse_int(limit, "limit", minimum=1, maximum=MAX_LIMIT)
    # .order_by() here is defensive, not load-bearing — measured, not assumed.
    # Django folds *explicitly* ordered fields into a values().annotate() GROUP
    # BY, but not a model's Meta.ordering, and this starts from the manager. It
    # is kept so this stays correct if handed an ordered queryset later; the
    # viewer's level counts, which aggregate an already-ordered queryset, do
    # genuinely need it.
    rows = (
        LogRecord.objects.order_by()
        .values("logger")
        .annotate(count=Count("pk"))
        .order_by("-count", "logger")[:resolved]
    )
    return {"loggers": [{"logger": r["logger"], "count": r["count"]} for r in rows]}


def capture_status() -> dict:
    """Current window plus this process's handler stats.

    ``dropped`` is the field that turns a baffling session into an obvious one:
    it says the missing lines were dropped under load, not never logged. Stats
    are necessarily per-process — whichever worker answered — and the payload
    says so rather than implying fleet-wide numbers.
    """
    from .handlers import get_handlers

    window = capture.active_window()
    handlers = get_handlers()
    return {
        "open": window is not None,
        "level": window.level if window else None,
        "expires_at": window.expires_at.isoformat() if window else None,
        "started_at": window.started_at.isoformat() if window else None,
        "started_by": window.started_by if window else None,
        "note": window.note if window else None,
        "baseline_level": logging.getLevelName(capture.baseline_level()),
        "max_minutes": capture.max_capture_minutes(),
        # Read off a live handler rather than hardcoded, so it can't drift from
        # the interval the poller actually uses.
        "poll_after_seconds": handlers[0].poll_interval if handlers else 5.0,
        "handler_stats_scope": "this process only",
        "handlers": [h.stats() for h in handlers],
    }


def config_snapshot() -> dict:
    """Effective telemetry configuration — the provisioning check.

    Answers *is capture on, is my logger covered by TELEMETRY_CAPTURE_LOGGERS,
    am I dropping records* — questions a caller otherwise has to infer from an
    empty result set, which looks identical to "nothing went wrong".
    """
    from .handlers import DEFAULT_EXCLUDE_LOGGERS, get_handlers

    handlers = get_handlers()
    return {
        "capture_enabled": getattr(settings, "TELEMETRY_LOG_CAPTURE_ENABLED", True),
        "baseline_level": getattr(settings, "TELEMETRY_LOG_LEVEL", "WARNING"),
        "capture_loggers": list(getattr(settings, "TELEMETRY_CAPTURE_LOGGERS", [])),
        "excluded_loggers": list(DEFAULT_EXCLUDE_LOGGERS),
        "max_capture_minutes": capture.max_capture_minutes(),
        "retention_days": getattr(settings, "TELEMETRY_LOG_RETENTION_DAYS", 7),
        "max_rows": getattr(settings, "TELEMETRY_LOG_MAX_ROWS", 20000),
        "queue_size": getattr(settings, "TELEMETRY_LOG_QUEUE_SIZE", 1000),
        # Distinct from capture_enabled: a process can be configured for capture
        # and still have no handler installed (LOGGING overridden, as the test
        # settings do). Answering both saves a confusing round of debugging.
        "handler_installed": bool(handlers),
        "handler_stats_scope": "this process only",
        "handlers": [h.stats() for h in handlers],
        "stored_records": LogRecord.objects.count(),
        "writable": False,  # settings come from env/settings.py, never this surface
    }


# --- the one write ---------------------------------------------------------


def open_capture(*, level: Any = "DEBUG", minutes: Any = 15, note: Any = "", actor=None, actor_name: str = "") -> dict:
    """Open a capture window. ``note`` is required on every programmatic path.

    The CLI leaves ``--note`` optional because a human running it is present and
    accountable in the moment. An API or agent call is neither, so it has to say
    why — a human reads that note in the viewer while wondering who turned
    production verbosity up.

    ``actor`` (a user) is used for the audit entry; ``actor_name`` is the string
    stamped on the window. Auditing lives here so all three transports record it
    identically, and it uses ``log_action``/``LogEntry`` — never ``logger.*`` —
    because a log line about reading logs would be captured and returned by the
    next read.
    """
    text = str(note or "").strip()
    if not text:
        raise TelemetryQueryError(
            "note is required — say why capture is being turned up; it is shown to "
            "operators in the capture list"
        )

    resolved_level = parse_capture_level(level)
    resolved_minutes = parse_int(minutes if minutes not in (None, "") else 15, "minutes", minimum=1)
    ceiling = capture.max_capture_minutes()

    window = capture.start(
        level=resolved_level,
        minutes=resolved_minutes,
        actor=(actor_name or getattr(actor, "get_username", lambda: "")())[:150],
        note=text[:200],
    )

    if actor is not None:
        from apps.smallstack.audit import ADDITION, log_action

        log_action(actor, window, ADDITION, f"Opened {window.level} log capture")

    state = capture_status()
    # Report the clamp rather than silently running a different duration than
    # was asked for: a caller that requested 8 hours would otherwise stop
    # polling long after capture ended and conclude the feature is broken.
    state["requested_minutes"] = resolved_minutes
    state["clamped"] = resolved_minutes > ceiling
    return state


def close_capture(*, actor=None) -> dict:
    """Close any open window. Idempotent — closing nothing is a success.

    A caller's cleanup step runs in a ``finally``; it must not fail because the
    window already expired on its own.
    """
    window = capture.active_window()
    closed = capture.stop()

    if closed and window is not None and actor is not None:
        from apps.smallstack.audit import CHANGE, log_action

        log_action(actor, window, CHANGE, "Closed log capture early")

    return {"open": False, "closed": closed}
