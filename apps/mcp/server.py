"""MCP server registry: singleton Server, @tool decorator, per-request ToolContext.

The HTTP layer (views.py) reads TOOL_REGISTRY for tools/list and dispatches
through TOOL_HANDLERS for tools/call. Tool callbacks read `current_context()`
to get the authenticated user/token, set by views.py before invoking.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterator, Optional

logger = logging.getLogger("smallstack.mcp.server")


# No MCP SDK object lives here. SmallStack speaks the protocol itself — the
# JSON-RPC envelope, initialize/tools-list/tools-call dispatch, and OAuth are
# plain Django in `views.py`, served by gunicorn like every other route. The
# `mcp` SDK used to be imported here for a singleton `Server` that nothing ever
# read; removing it also drops pydantic/starlette/uvicorn/httpx/jsonschema from
# the install. `MCP_SERVER_NAME` is still used — views.py reports it in the
# `initialize` response.


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass
class ToolDef:
    """Tool metadata. The handler is stored separately in TOOL_HANDLERS."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    write: bool = False
    requires_access: Optional[str] = None  # "readonly" | "staff" | "auth" | None
    # Optional callable applied at tools/list time. ``(user) -> bool``.
    # When set and it returns False, the tool is hidden from that user's
    # tools/list response. Useful for tools where the access decision
    # isn't expressible as a flat ``requires_access`` level — the search
    # MCP tools (round-2 audit §3.3) gate by the underlying view's
    # ``search_access`` tier, which check_tool_access can't see. Without
    # this hook the tool was visible-but-non-functional to non-staff
    # callers — they saw ``search_users`` in the list and got
    # ``{"denied": true}`` on call. Returning False here hides it
    # from the list AND tools/call's existing check_tool_access still
    # gates the call itself (defense in depth).
    visible_to: Optional[Callable[[Any], bool]] = None


# Module-level registries — populated by @tool, read by views.py + factory.
TOOL_REGISTRY: dict[str, ToolDef] = {}
TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    *,
    write: bool = False,
    requires_access: str | None = None,
    visible_to: Callable[[Any], bool] | None = None,
) -> Callable[[Callable], Callable]:
    """Register an async tool callback with the MCP server.

    Usage:
        @tool("today", "Return today's local date and weekday.")
        async def today(args: dict) -> dict:
            ctx = current_context()
            return {"date": ..., "user": ctx.user.username}

    Idempotent: registering the same name twice logs a warning and keeps
    the first registration (so the factory can be re-run safely).
    """

    def decorator(fn: Callable[[dict[str, Any]], Awaitable[Any]]) -> Callable:
        if name in TOOL_REGISTRY:
            logger.warning("MCP tool %r already registered — skipping duplicate", name)
            return fn
        TOOL_REGISTRY[name] = ToolDef(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            write=write,
            requires_access=requires_access,
            visible_to=visible_to,
        )
        TOOL_HANDLERS[name] = fn
        logger.debug("MCP registered tool %r (write=%s, requires=%s)", name, write, requires_access)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Per-request context (user + token visible to tool callbacks)
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    user: Any  # AUTH_USER_MODEL instance
    token: Any  # APIToken instance


_context_var: ContextVar[ToolContext | None] = ContextVar("mcp_tool_context", default=None)


def set_context(ctx: ToolContext | None) -> Any:
    """Set the current tool context. Returns a token usable with reset_context."""
    return _context_var.set(ctx)


def reset_context(token: Any) -> None:
    _context_var.reset(token)


def current_context() -> ToolContext:
    """Return the active ToolContext.

    Raises LookupError if called outside a tool dispatch — tool callbacks
    should rely on this; helpers shared across HTTP + tool paths must check
    `try: current_context() except LookupError`.
    """
    ctx = _context_var.get()
    if ctx is None:
        raise LookupError("ToolContext is not set. current_context() called outside a tool dispatch.")
    return ctx


def clear_registry_for_tests() -> None:
    """Test helper: wipe the registries between tests. Do not use in prod.

    This empties the *process-wide* registries that every app populated at
    startup. The project-root ``conftest.py`` snapshots both before every
    test and restores them afterwards (``isolated_tool_registry``), so a
    test that calls this cannot starve a later test of the startup tools —
    whatever order pytest runs the files in.
    """
    TOOL_REGISTRY.clear()
    TOOL_HANDLERS.clear()


@contextmanager
def isolated_tool_registry() -> Iterator[None]:
    """Snapshot ``TOOL_REGISTRY`` / ``TOOL_HANDLERS`` and restore them on exit.

    The registries are module-level dicts filled during ``AppConfig.ready()``;
    nothing re-populates them later in the process. A test that wipes or
    mutates them must therefore put the startup state back, or every later
    test that asserts "my app's tools are registered" fails depending purely
    on file order. The root ``conftest.py`` applies this around every test.
    """
    tools = dict(TOOL_REGISTRY)
    handlers = dict(TOOL_HANDLERS)
    try:
        yield
    finally:
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(tools)
        TOOL_HANDLERS.clear()
        TOOL_HANDLERS.update(handlers)
