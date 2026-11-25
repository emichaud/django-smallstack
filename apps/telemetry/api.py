"""Read-only REST surface for captured log records — ``/api/logger/``.

The staff viewer at ``/smallstack/logs/`` is the *human* surface, and it stays
exactly as it is. This is the surface a **machine** uses: a CI job asserting an
error was logged, a frontend dev panel resolving an ``X-Request-ID``, and above
all an AI agent driving a debugging session with nothing but an API token —
turn capture up, reproduce, read the lines, correlate, turn capture back down.

Two consumers, two shapes. The differences are deliberate:

* **Cursor, not page numbers.** ``?after_id=`` returns records strictly newer
  than a known id (tailing); ``?before_id=`` the next older page of a
  newest-first listing, from the previous page's ``next_before_id``. Page
  numbers are wrong for a live tail: new rows arrive at the top and shift
  everything down, so page 2 re-reads what page 1 already
  returned. A human scrolling doesn't notice; a polling loop double-counts.
* **Unknown query parameters are a 400.** A human eventually notices a result
  set looks wrong. An agent does not — ``?sevrity=ERROR`` would silently return
  the *unfiltered* table, which reads as a successful query, and every
  conclusion drawn afterwards is built on it. Failing loudly costs one retry.
* **Bounded payloads.** One traceback can be 20 KB; fifty of them would fill an
  agent's context for no benefit. Lists truncate ``exc_text`` and flag it with
  ``exc_truncated``; the detail endpoint serves the full text for the one
  record that matters.
* **``applied_filters`` is echoed back**, so a caller can verify the server
  understood the query it thinks it sent.

Filter *semantics* are shared with the viewer rather than reimplemented — same
"this level and above", same hierarchy-aware logger prefix (``logger_match``),
same message-plus-traceback search. Two implementations of "what does
``logger=apps.telemetry`` mean" would eventually disagree, and the round-2
sibling-prefix finding was exactly that bug in one of them.

Reads are staff-scoped; the single write — opening and closing a capture
window — is refused for read-only tokens, so a CI job or a monitoring script
can assert an error was logged without being able to turn DEBUG on in
production. See ``docs/logger-api-spec.md``.

Auditing note: reads are deliberately **not** logged through the logging system
being read. A ``logger.info()`` here would be captured, so reading logs would
create records that the next read returns — the same feedback shape
``DatabaseLogHandler``'s thread-local recursion guard exists to break, one
level up. ``/api/logger/`` is also excluded from activity logging by default
(``ACTIVITY_EXCLUDE_PATHS``) so an agent polling a tail doesn't fill the table
it is reading with its own poll traffic.
"""

from __future__ import annotations

from apps.smallstack.api import api_error, api_view, register_api_path

from .queries import (
    DEFAULT_LIMIT,
    FILTER_NAMES,
    LEVELS,
    LIST_EXC_CHARS,
    LIST_MESSAGE_CHARS,
    MAX_LIMIT,
    TelemetryQueryError,
    capture_status,
    close_capture,
    config_snapshot,
    get_record,
    logger_counts,
    open_capture,
    reject_unknown,
    search_records,
)

# Kept as a module-level name because the capability document and its test both
# assert the advertised filter list matches what is implemented.
RECORD_FILTERS = frozenset(FILTER_NAMES)


def _guard(fn):
    """Render a TelemetryQueryError as the standard 400 envelope.

    Validation lives in queries.py so all three transports reject the same
    inputs with the same words; this only decides the status code.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(request, *args, **kwargs):
        try:
            return fn(request, *args, **kwargs)
        except TelemetryQueryError as exc:
            return api_error(str(exc), 400)

    return wrapper


@api_view(methods=["GET"], require_staff=True)
@_guard
def api_logger_index(request):
    """Capability document — what a caller reads before anything else.

    Exists so a client doesn't have to hardcode the contract: the filter list,
    the limits, and the current capture state in one round trip.
    """
    # The unknown-param rule applies here too. The endpoint whose job is to
    # describe the contract must not be the one place that quietly accepts
    # anything.
    reject_unknown(request.GET.keys(), ())
    status = capture_status()
    return {
        "version": "1",
        "capture": {
            "open": status["open"],
            "baseline_level": status["baseline_level"],
            "max_minutes": status["max_minutes"],
        },
        "endpoints": {
            "records": "/api/logger/records/",
            "record_detail": "/api/logger/records/{id}/",
            "capture": "/api/logger/capture/",
            "config": "/api/logger/config/",
            "loggers": "/api/logger/loggers/",
        },
        "filters": sorted(RECORD_FILTERS),
        "levels": list(LEVELS),
        "limits": {
            "max_limit": MAX_LIMIT,
            "default_limit": DEFAULT_LIMIT,
            "list_message_chars": LIST_MESSAGE_CHARS,
            "list_exc_chars": LIST_EXC_CHARS,
        },
        # Advertised so a client can tell whether it may turn capture up before
        # trying — a read-only token reads everything here but writes nothing.
        "writes_enabled": True,
        "capture_write": {
            "methods": ["POST", "DELETE"],
            "fields": {"level": "|".join(LEVELS), "minutes": "int, clamped", "note": "required"},
        },
    }


@api_view(methods=["GET"], require_staff=True)
@_guard
def api_logger_records(request):
    """Search captured log records."""
    reject_unknown(request.GET.keys(), RECORD_FILTERS)
    return search_records(**{name: request.GET[name] for name in RECORD_FILTERS if name in request.GET})


@api_view(methods=["GET"], require_staff=True)
@_guard
def api_logger_record_detail(request, record_id: int):
    """One record, untruncated — the full traceback and extra fields."""
    reject_unknown(request.GET.keys(), ())
    record = get_record(record_id)
    if record is None:
        return api_error("Log record not found", 404)
    return record


@api_view(methods=["GET", "POST", "DELETE"], require_staff=True)
@_guard
def api_logger_capture(request):
    """Read, open, or close the capture window.

    The one runtime write in this surface, and the reason a client can run a
    debugging session unattended: baseline capture is WARNING, so the INFO
    breadcrumbs explaining a bug are not in the table until someone turns the
    volume up. Read-only tokens are refused for POST/DELETE by ``api_view``.
    """
    if request.method == "GET":
        reject_unknown(request.GET.keys(), ())
        return capture_status()

    if request.method == "DELETE":
        return close_capture(actor=request.user)

    payload = request.json or {}
    reject_unknown(payload.keys(), ("level", "minutes", "note"), kind="field")
    return open_capture(
        level=payload.get("level", "DEBUG"),
        minutes=payload.get("minutes", 15),
        note=payload.get("note", ""),
        actor=request.user,
    ), 201


@api_view(methods=["GET"], require_staff=True)
@_guard
def api_logger_config(request):
    """Effective telemetry configuration — deliberately read-only.

    There is no PUT. Persistent configuration belongs in settings/env where a
    deploy reproduces it; an API that rewrote baseline logging config would be a
    configuration-drift generator and a dangerous thing to mint a token for. The
    capture window is the one legitimate runtime knob, and it expires.
    """
    reject_unknown(request.GET.keys(), ())
    return config_snapshot()


@api_view(methods=["GET"], require_staff=True)
@_guard
def api_logger_loggers(request):
    """Which loggers have produced records, and how many."""
    reject_unknown(request.GET.keys(), ("limit",))
    return logger_counts(request.GET.get("limit", 100))


# --- OpenAPI ---------------------------------------------------------------
# Hand-rolled @api_view endpoints don't self-register the way CRUDView ones do.
# Without this the surface is invisible in Swagger/ReDoc — and an agent that
# discovers capabilities by reading the schema would never learn it exists.

_LOGGER_TAG = ["Logger"]

register_api_path(
    "api-logger-index",
    methods=["GET"],
    summary="Logger API capability document (filters, limits, capture state)",
    tags=_LOGGER_TAG,
)
register_api_path(
    "api-logger-records",
    methods=["GET"],
    summary="Search captured log records",
    tags=_LOGGER_TAG,
    parameters=[
        {
            "name": name,
            "in": "query",
            "required": False,
            "schema": {"type": "integer"} if name in ("after_id", "before_id", "limit") else {"type": "string"},
            "description": desc,
        }
        for name, desc in [
            ("level", "This level and above (DEBUG, INFO, WARNING, ERROR, CRITICAL)."),
            ("logger", "Hierarchy-aware logger prefix; a parent includes its children."),
            ("request_id", "Exact match — the X-Request-ID from a failing response."),
            ("trace_id", "Exact match — correlates background task / scheduler work."),
            ("search", "Substring across the message and the traceback."),
            ("since", "ISO-8601 lower bound on the timestamp."),
            ("until", "ISO-8601 upper bound on the timestamp."),
            ("after_id", "Cursor: records newer than this id, oldest-first. Use for tailing."),
            ("before_id", "Cursor: the next older page, newest-first. Pass the previous page's next_before_id."),
            ("limit", f"Page size, default {DEFAULT_LIMIT}, max {MAX_LIMIT}."),
        ]
    ],
    responses={
        "200": {"description": "Matching records, with has_more, next_before_id (older) and next_after_id (newer)"},
        "400": {"description": "Unknown or invalid query parameter"},
        "403": {"description": "Staff access required"},
    },
)
register_api_path(
    "api-logger-records",
    methods=["GET"],
    subpath="{id}/",
    summary="One log record, with the full untruncated traceback",
    tags=_LOGGER_TAG,
    parameters=[
        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}},
    ],
    responses={"200": {"description": "The record"}, "404": {"description": "Not found"}},
)
register_api_path(
    "api-logger-capture",
    methods=["GET", "POST", "DELETE"],
    summary="Read, open (POST), or close (DELETE) the log capture window",
    tags=_LOGGER_TAG,
    request_body={
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["note"],
                    "properties": {
                        "level": {"type": "string", "enum": list(LEVELS), "default": "DEBUG"},
                        "minutes": {"type": "integer", "default": 15},
                        "note": {"type": "string", "description": "Why capture is being turned up."},
                    },
                }
            }
        }
    },
    responses={
        "200": {"description": "Status (GET) or window closed (DELETE)"},
        "201": {"description": "Capture window opened"},
        "400": {"description": "Missing note, unknown field, or invalid level/minutes"},
        "403": {"description": "Staff access required, or the token is read-only"},
    },
)
register_api_path(
    "api-logger-config",
    methods=["GET"],
    summary="Effective telemetry settings and live handler stats (read-only)",
    tags=_LOGGER_TAG,
)
register_api_path(
    "api-logger-loggers",
    methods=["GET"],
    summary="Logger names that have produced records, with counts",
    tags=_LOGGER_TAG,
)
