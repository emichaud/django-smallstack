"""The simulated privileged actions an agent may propose.

Deliberately pure + deterministic: each handler takes the payload and returns a
one-line result string. Nothing here touches the outside world — the point of
Scenario B is the *gate*, not the side effect.

Two failure paths are modelled on purpose, because the docs promise different
behaviour for each:

* a handler that raises (``records.purge`` with a bad count, or an unknown
  tool) → the callback catches it and records ``state=failed`` with the error in
  ``result``: an app-level failure, the decision still stands.
* the reserved ``RAISE_IN_CALLBACK_KEY`` payload flag → the callback itself
  raises, which is what ``ApprovalRequest.callback_error`` exists for
  (docs/skills/approvals.md §4.1).
"""

from __future__ import annotations

from typing import Any, Callable

# Payload flag that makes the kind callback raise *outside* its own error
# handling, to exercise the callback_error surface.
RAISE_IN_CALLBACK_KEY = "__raise_in_callback"


class UnknownTool(Exception):
    """The agent proposed a tool this app cannot execute."""


def _broadcast_send(payload: dict[str, Any]) -> str:
    audience = str(payload.get("audience") or "all-users")
    subject = str(payload.get("subject") or "(no subject)")
    return f"broadcast queued to {audience}: {subject}"


def _records_purge(payload: dict[str, Any]) -> str:
    raw = payload.get("count")
    if not isinstance(raw, (int, str)) or isinstance(raw, bool):
        raise ValueError(f"records.purge needs an integer 'count', got {raw!r}")
    try:
        count = int(raw)
    except ValueError:
        raise ValueError(f"records.purge needs an integer 'count', got {raw!r}") from None
    if count < 0:
        raise ValueError("records.purge 'count' must not be negative")
    return f"purged {count} records from {payload.get('table') or 'unknown table'}"


def _runbook_execute(payload: dict[str, Any]) -> str:
    slug = str(payload.get("slug") or "")
    if not slug:
        raise ValueError("runbook.execute needs a 'slug'")
    return f"executed runbook {slug}"


HANDLERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "broadcast.send": _broadcast_send,
    "records.purge": _records_purge,
    "runbook.execute": _runbook_execute,
}

TOOL_NAMES: list[str] = sorted(HANDLERS)


def execute(tool_name: str, payload: dict[str, Any]) -> str:
    """Run the simulated action. Raises on any failure; the caller records it."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        raise UnknownTool(f"No handler for {tool_name!r}. Known tools: {', '.join(TOOL_NAMES)}")
    return handler(payload or {})
