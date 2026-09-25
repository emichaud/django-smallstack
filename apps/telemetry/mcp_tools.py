"""MCP tools for reading logs and controlling capture.

Auto-discovered by ``apps.mcp``. These are the same operations as
``/api/logger/`` and ``manage.py log_capture``, over a third transport — and
deliberately the same *code*: every handler is a thin async wrapper around
``queries.py``. A filter that means one thing over HTTP and another to an agent
would be worse than not shipping the tools at all.

Why an agent gets tools rather than being told to curl the API: it picks tools
by reading their descriptions, so the descriptions here carry the workflow
("paste the X-Request-ID from a failing response into request_id"), and the
argument schemas make the contract checkable before a call rather than after a
400.

Five tools, not eight. Every tool costs room in the agent's tool list, and
"what's the state of logging here" is one question, so ``logs_status`` answers
capture state, effective configuration, and the busiest loggers together —
which is also the orientation call an agent should make first.

Access is deliberately identical to the REST surface, which took a correction
worth recording. MCP's ``requires_access`` gates on the **token's** access
level, while ``/api/logger/``'s ``require_staff`` gates on the **user**. Those
are different questions: nothing stops a staff-*level* token being minted for a
non-staff user. Since the 2026-09-13 audit (C1), ``check_tool_access`` also
requires ``token.user.is_staff`` for any ``requires_access`` of "staff" or
above, so the framework now enforces this too — the handler-level check below
stays as defence in depth and as the source of a readable error message.

So, matching REST exactly:

* every handler calls :func:`_require_staff_user`, so the **user** must be
  staff — logs carry request paths, user identifiers, and tracebacks;
* ``visible_to`` hides the tools from non-staff callers entirely, so an agent
  is not offered a tool it cannot use;
* the two capture tools are ``write=True``, which the MCP auth layer already
  translates into "read-only tokens are refused" — so a read-only credential
  belonging to a staff user can investigate without being able to turn DEBUG on
  in production, exactly as on the REST side.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from apps.mcp.server import current_context, tool

from . import queries

logger = logging.getLogger(__name__)

_LEVEL_ENUM = list(queries.LEVELS)


# Registration is recorded as well as performed, so it can be repeated. The
# MCP test suite calls ``clear_registry_for_tests()``, which wipes the shared
# registry — including tools registered at import time, which a cached module
# will not re-register. Without a way to re-run it, whether these tools exist
# depends on test ordering (the same trap apps/runbook/tests/conftest.py
# already documents). ``tool()`` itself is idempotent by name.
_SPECS: list[tuple] = []


def _register(name: str, description: str, schema: dict, **opts):
    def decorator(fn):
        _SPECS.append((name, description, schema, opts, fn))
        tool(name, description, schema, **opts)(fn)
        return fn

    return decorator


def register_telemetry_tools() -> int:
    """Re-apply every registration. Idempotent; returns how many tools."""
    for name, description, schema, opts, fn in _SPECS:
        tool(name, description, schema, **opts)(fn)
    return len(_SPECS)


def _staff_only(user) -> bool:
    """Visibility gate — non-staff callers don't see these tools listed."""
    return bool(getattr(user, "is_staff", False))


def _require_staff_user() -> dict | None:
    """Enforce the same rule ``/api/logger/`` enforces: the USER must be staff.

    Not redundant with ``visible_to``: that only hides a tool from tools/list,
    and a caller can name any tool in tools/call regardless of what was listed.
    """
    try:
        ctx = current_context()
    except LookupError:  # pragma: no cover - only outside a dispatch
        return {"error": "No MCP context; this tool must be called through the MCP server."}
    if not getattr(getattr(ctx, "user", None), "is_staff", False):
        return {"error": "Staff access required to read logs."}
    return None


def _error(exc: queries.TelemetryQueryError) -> dict:
    """Render a validation failure as data the model can act on.

    Returned rather than raised: an agent recovers from `{"error": "level must
    be one of …"}` by correcting the argument, whereas an exception surfaces as
    a tool failure it is more likely to abandon or retry unchanged.
    """
    return {"error": str(exc)}


# --- read ------------------------------------------------------------------


@_register(
    "logs_search",
    (
        "Search captured application log records. The main way to find out what a running "
        "SmallStack app actually logged. Filter by request_id using the X-Request-ID header "
        "from a failing HTTP response to get every line that request produced, or by trace_id "
        "for a background task or scheduled job. `search` matches the message AND the "
        "traceback, so an exception class name works. `level` means that level and above. "
        "`logger` is a hierarchy-aware prefix: 'apps' includes 'apps.inventory.views'. "
        "To tail, pass the previous result's next_after_id as after_id. "
        "If results are empty, call logs_status — capture may be at its WARNING baseline, "
        "in which case INFO/DEBUG lines were never stored and you need logs_capture_start."
    ),
    {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": _LEVEL_ENUM, "description": "This level and above."},
            "logger": {"type": "string", "description": "Hierarchy-aware logger prefix."},
            "request_id": {"type": "string", "description": "Exact X-Request-ID to correlate."},
            "trace_id": {"type": "string", "description": "Exact trace id (background work)."},
            "search": {"type": "string", "description": "Substring of the message or traceback."},
            "since": {"type": "string", "description": "ISO-8601 lower bound, e.g. 2026-08-17T01:30:00Z."},
            "until": {"type": "string", "description": "ISO-8601 upper bound."},
            "after_id": {"type": "integer", "description": "Cursor: only records newer than this id."},
            "limit": {"type": "integer", "description": f"Max {queries.MAX_LIMIT}, default {queries.DEFAULT_LIMIT}."},
        },
        "additionalProperties": False,
    },
    visible_to=_staff_only,
)
async def logs_search(args: dict) -> dict:
    denied = _require_staff_user()
    if denied:
        return denied
    try:
        queries.reject_unknown(args.keys(), queries.FILTER_NAMES, kind="argument")
        return await sync_to_async(queries.search_records)(**args)
    except queries.TelemetryQueryError as exc:
        return _error(exc)


@_register(
    "logs_get",
    (
        "Get one log record by id, with the FULL traceback and extra fields — list results "
        "truncate both. Use after logs_search narrows things down to the one line that matters."
    ),
    {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "Record id from logs_search."}},
        "required": ["id"],
        "additionalProperties": False,
    },
    visible_to=_staff_only,
)
async def logs_get(args: dict) -> dict:
    denied = _require_staff_user()
    if denied:
        return denied
    try:
        queries.reject_unknown(args.keys(), ("id",), kind="argument")
        record = await sync_to_async(queries.get_record)(args.get("id"))
    except queries.TelemetryQueryError as exc:
        return _error(exc)
    return record or {"error": f"No log record with id {args.get('id')!r}"}


@_register(
    "logs_status",
    (
        "How logging is configured and what is being captured right now — the orientation call "
        "to make before investigating. Answers: is capture enabled, what level is being stored "
        "(baseline is usually WARNING, so INFO/DEBUG are NOT stored unless a capture window is "
        "open), is a window open and when does it expire, which loggers are covered, and are "
        "records being dropped under load. A non-zero `dropped` means lines were lost rather "
        "than never logged. Also lists the busiest logger names, so you know what to pass to "
        "logs_search's `logger` filter instead of guessing."
    ),
    {"type": "object", "properties": {}, "additionalProperties": False},
    visible_to=_staff_only,
)
async def logs_status(args: dict) -> dict:
    denied = _require_staff_user()
    if denied:
        return denied
    try:
        queries.reject_unknown(args.keys(), (), kind="argument")
    except queries.TelemetryQueryError as exc:
        return _error(exc)

    def _gather() -> dict:
        return {
            "capture": queries.capture_status(),
            "config": queries.config_snapshot(),
            "top_loggers": queries.logger_counts(20)["loggers"],
        }

    return await sync_to_async(_gather)()


# --- write -----------------------------------------------------------------


@_register(
    "logs_capture_start",
    (
        "Temporarily turn log capture up so lines below the baseline level (usually WARNING) "
        "get stored. Use when logs_search finds nothing and you need to reproduce a problem "
        "with INFO/DEBUG breadcrumbs visible. The window applies to every worker and container "
        "within a few seconds, and CLOSES ITSELF when it expires — but call logs_capture_stop "
        "when you are done rather than leaving it running. `note` is required: say what you are "
        "investigating, because a human sees it in the log viewer and it is how they know who "
        "turned production verbosity up and why."
    ),
    {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": _LEVEL_ENUM, "description": "Default DEBUG."},
            "minutes": {"type": "integer", "description": "Default 15; clamped to the configured maximum."},
            "note": {"type": "string", "description": "Required. Why capture is being turned up."},
        },
        "required": ["note"],
        "additionalProperties": False,
    },
    write=True,
    visible_to=_staff_only,
)
async def logs_capture_start(args: dict) -> dict:
    denied = _require_staff_user()
    if denied:
        return denied
    try:
        queries.reject_unknown(args.keys(), ("level", "minutes", "note"), kind="argument")
        ctx = current_context()
        return await sync_to_async(queries.open_capture)(
            level=args.get("level", "DEBUG"),
            minutes=args.get("minutes", 15),
            note=args.get("note", ""),
            actor=getattr(ctx, "user", None),
        )
    except queries.TelemetryQueryError as exc:
        return _error(exc)


@_register(
    "logs_capture_stop",
    (
        "Close the capture window and return logging to its baseline level. Safe to call when "
        "no window is open (returns closed: 0), so it is the correct cleanup step after any "
        "investigation, successful or not."
    ),
    {"type": "object", "properties": {}, "additionalProperties": False},
    write=True,
    visible_to=_staff_only,
)
async def logs_capture_stop(args: dict) -> dict:
    denied = _require_staff_user()
    if denied:
        return denied
    try:
        queries.reject_unknown(args.keys(), (), kind="argument")
        ctx = current_context()
        return await sync_to_async(queries.close_capture)(actor=getattr(ctx, "user", None))
    except queries.TelemetryQueryError as exc:
        return _error(exc)
