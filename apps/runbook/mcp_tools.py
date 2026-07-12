"""MCP tools exposing the document service to agents (Claude Desktop, etc.).

Auto-discovered by the SmallStack MCP app. Handlers are thin, sync, and call the
same service layer as the web/REST paths, so versioning, provenance, retention,
and events are identical. The ``do_*`` functions take an explicit actor so they
are testable without an MCP dispatch context.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from . import service


def _json_safe(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _result(result: service.DocumentResult) -> dict:
    return {k: _json_safe(v) for k, v in dataclasses.asdict(result).items()}


def _summary(summary: service.DocumentSummary) -> dict:
    return {k: _json_safe(v) for k, v in dataclasses.asdict(summary).items()}


# -- Testable delegates (explicit actor; no MCP context required) -------------

def do_list(*, runbook: Optional[str] = None, source: Optional[str] = None,
            query: Optional[str] = None, limit: int = 50, viewer: service.Actor = None) -> dict:
    try:
        docs = service.list_documents(
            runbook=runbook or None, source=source or None, query=query or None, viewer=viewer
        )
    except service.DocumentServiceError as exc:
        return {"error": str(exc)}
    return {"results": [_summary(d) for d in docs[:limit]]}


def do_get(*, runbook: Optional[str] = None, key: Optional[str] = None,
           id: Optional[int] = None, uid: Optional[str] = None, viewer: service.Actor = None) -> dict:
    try:
        return _result(service.get_document(runbook, key, id=id, uid=uid, with_body=True, viewer=viewer))
    except service.DocumentNotFound as exc:
        return {"error": str(exc)}


def do_put(actor: service.Actor, *, runbook: str, key: str, body: str, title: Optional[str] = None,
           on_exists: str = "new_version", expected_version: Optional[int] = None,
           source: str = "", section: Optional[str] = None, doc_type: str = "") -> dict:
    try:
        result = service.put_document(
            runbook, key, body=body, title=title, on_exists=on_exists,
            expected_version=expected_version, source=source or "mcp", section=section,
            doc_type=doc_type, via="mcp", actor=actor,
        )
    except service.DocumentServiceError as exc:
        return {"error": str(exc)}
    return _result(result)


def do_append(actor: service.Actor, *, runbook: str, key: str, body: str, source: str = "") -> dict:
    try:
        result = service.append_to_document(
            runbook, key, body=body, source=source or "mcp", via="mcp", actor=actor
        )
    except service.DocumentServiceError as exc:
        return {"error": str(exc)}
    return _result(result)


def do_move(actor: service.Actor, *, runbook: Optional[str] = None, key: Optional[str] = None,
            uid: Optional[str] = None, to_runbook: Optional[str] = None,
            to_section: Optional[str] = None) -> dict:
    try:
        result = service.move_document(
            runbook=runbook, key=key, uid=uid, to_runbook=to_runbook, to_section=to_section, actor=actor
        )
    except service.DocumentServiceError as exc:
        return {"error": str(exc)}
    return _result(result)


def do_delete(actor: service.Actor, *, runbook: Optional[str] = None, key: Optional[str] = None,
              uid: Optional[str] = None, force: bool = False) -> dict:
    try:
        service.delete_document(runbook=runbook, key=key, uid=uid, force=force, actor=actor)
    except service.DocumentServiceError as exc:
        return {"error": str(exc)}
    return {"deleted": True, "force": force}


# -- MCP registration (only when the SmallStack MCP app is present) -----------

try:
    from apps.mcp.server import current_context, tool
except ImportError:  # pragma: no cover - MCP app not installed downstream

    def register_runbook_tools() -> None:
        """No-op — the SmallStack MCP app isn't installed."""


else:

    def _actor() -> service.Actor:
        return current_context().user

    _RUNBOOK_KEY_PROPS = {
        "runbook": {"type": "string", "description": "Runbook slug (the namespace)."},
        "key": {"type": "string", "description": "Stable document key, unique per runbook."},
    }

    def register_runbook_tools() -> None:
        """Register the ``runbook_*`` MCP tools.

        Idempotent — ``apps.mcp.server.tool`` dedups by name — so it's safe to
        call at import time (for startup) and again from the test suite after
        ``clear_registry_for_tests()`` wipes the shared MCP registry.
        """
        tool(
            "runbook_list_documents",
            "List runbook documents (optionally filtered by runbook, source, or a text query).",
            {
                "type": "object",
                "properties": {
                    "runbook": {"type": "string", "description": "Runbook slug to scope to."},
                    "source": {"type": "string", "description": "Filter by provenance source label."},
                    "query": {"type": "string", "description": "Case-insensitive title/content search."},
                    "limit": {"type": "integer", "description": "Max results (default 50).", "default": 50},
                },
            },
            requires_access="readonly",
        )(lambda args: do_list(
            runbook=args.get("runbook"), source=args.get("source"),
            query=args.get("query"), limit=int(args.get("limit") or 50), viewer=_actor(),
        ))

        tool(
            "runbook_get_document",
            "Fetch a runbook document (with its markdown body) by (runbook, key) or by id.",
            {
                "type": "object",
                "properties": {
                    **_RUNBOOK_KEY_PROPS,
                    "uid": {"type": "string", "description": "Canonical document uid (alternative address)."},
                    "id": {"type": "integer", "description": "Document id (alternative address)."},
                },
            },
            requires_access="readonly",
        )(lambda args: do_get(
            runbook=args.get("runbook"), key=args.get("key"), id=args.get("id"), uid=args.get("uid"), viewer=_actor(),
        ))

        tool(
            "runbook_put_document",
            "Create or update a document addressed by (runbook, key). on_exists controls "
            "the write: new_version (default), overwrite, append, or fail.",
            {
                "type": "object",
                "properties": {
                    **_RUNBOOK_KEY_PROPS,
                    "body": {"type": "string", "description": "Markdown content."},
                    "title": {"type": "string", "description": "Title (set on create; updated if provided)."},
                    "on_exists": {
                        "type": "string",
                        "enum": ["new_version", "overwrite", "append", "fail"],
                        "default": "new_version",
                    },
                    "expected_version": {"type": "integer", "description": "Optimistic lock: reject if head differs."},
                    "source": {"type": "string", "description": "Provenance label, e.g. 'newsletter-bot'."},
                    "section": {"type": "string", "description": "Optional section slug within the runbook."},
                    "doc_type": {"type": "string", "description": "Optional classification for formatters."},
                },
                "required": ["runbook", "key", "body"],
            },
            write=True,
            requires_access="staff",
        )(lambda args: do_put(
            _actor(), runbook=args["runbook"], key=args["key"], body=args["body"],
            title=args.get("title"), on_exists=args.get("on_exists", "new_version"),
            expected_version=args.get("expected_version"), source=args.get("source", ""),
            section=args.get("section"), doc_type=args.get("doc_type", ""),
        ))

        tool(
            "runbook_append_document",
            "Append markdown to a document's current content in place (log-style accumulation).",
            {
                "type": "object",
                "properties": {
                    **_RUNBOOK_KEY_PROPS,
                    "body": {"type": "string", "description": "Markdown to append."},
                    "source": {"type": "string", "description": "Provenance label."},
                },
                "required": ["runbook", "key", "body"],
            },
            write=True,
            requires_access="staff",
        )(lambda args: do_append(
            _actor(), runbook=args["runbook"], key=args["key"], body=args["body"], source=args.get("source", ""),
        ))

        tool(
            "runbook_move_document",
            "Move a document to another runbook/section (identity by uid is unchanged). "
            "Omit to_runbook to detach it to a standalone document.",
            {
                "type": "object",
                "properties": {
                    **_RUNBOOK_KEY_PROPS,
                    "uid": {"type": "string", "description": "Canonical uid (alternative to runbook+key)."},
                    "to_runbook": {"type": "string", "description": "Destination runbook slug (omit to detach)."},
                    "to_section": {"type": "string", "description": "Optional destination section slug."},
                },
            },
            write=True,
            requires_access="staff",
        )(lambda args: do_move(
            _actor(), runbook=args.get("runbook"), key=args.get("key"), uid=args.get("uid"),
            to_runbook=args.get("to_runbook"), to_section=args.get("to_section"),
        ))

        tool(
            "runbook_delete_document",
            "Delete a document. Archives (recoverable) by default; force=true hard-deletes.",
            {
                "type": "object",
                "properties": {
                    **_RUNBOOK_KEY_PROPS,
                    "uid": {"type": "string", "description": "Canonical uid (alternative to runbook+key)."},
                    "force": {"type": "boolean", "description": "Hard-delete instead of archive.", "default": False},
                },
            },
            write=True,
            requires_access="staff",
        )(lambda args: do_delete(
            _actor(), runbook=args.get("runbook"), key=args.get("key"), uid=args.get("uid"),
            force=bool(args.get("force", False)),
        ))

    # Register at import time so the tools are present at startup.
    register_runbook_tools()
