"""Register search MCP tools.

For every CRUDView with ``enable_search = True``, register a
``search_<plural>(query, limit)`` tool with the MCP server. Also
register a cross-model ``search_all(query, limit_per_model)`` tool so
Claude can find anything matching across the whole site.

Tools follow the same async-handler shape as the existing factory tools
(see ``apps/mcp/factory.py``). The MCP server's TOOL_REGISTRY is a
process-level dict, so we just call ``tool(...)`` at startup time from
``SearchConfig.ready()``.

If ``apps.mcp`` isn't installed (downstream project chose to disable
MCP), the import is guarded and we silently skip — the search backend
still works for HTML + REST.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from .registry import all_views
from .registry import search_all as _search_all

logger = logging.getLogger("smallstack.search")


def register_search_tools() -> int:
    """Called from SearchConfig.ready(). Returns the number of tools registered."""
    try:
        from apps.mcp.server import tool
    except Exception:
        logger.info("apps.mcp not available — skipping search MCP tools")
        return 0

    count = 0

    # Per-CRUDView search_<plural> tools.
    for view in all_views():
        tool_name = _tool_name_for(view)
        description = (
            f"Search {view.model_verbose} records by free-text query against "
            f"fields {view.fields}. Returns ranked matches with display title, "
            f"snippet, and detail URL. Use this when the user asks 'find', "
            f"'search', or anything implying retrieval over {view.model_verbose}."
        )

        async def _handler(args: dict, *, _view=view):
            query = (args.get("query") or "").strip()
            limit = int(args.get("limit") or 10)
            if not query:
                return {"results": []}
            from .backends import get_backend

            backend = get_backend()
            hits = await sync_to_async(backend.query)(_view, query, limit)
            return {"results": [h.as_dict() for h in hits], "backend": backend.name}

        try:
            tool(
                tool_name,
                description,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search text."},
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10).",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
                requires_access="readonly",
            )(_handler)
            count += 1
        except Exception:
            logger.exception("Failed to register MCP tool %r", tool_name)

    # search_help — bundled-docs RAG. Always registered (the help system
    # always exists in a SmallStack clone).
    try:
        tool(
            "search_help",
            (
                "Search SmallStack's bundled help documentation (apps/smallstack/docs/) "
                "by free-text query. Returns matching articles with a title, section, "
                "snippet, and URL. Use this when the user asks how to configure, use, "
                "or extend SmallStack — for example: 'how do I add a custom palette?', "
                "'what's the MCP setup?', 'how does the search system work?'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search text."},
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 10).",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            requires_access="readonly",
        )(_search_help_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register search_help MCP tool")

    # Cross-model tool — always registered if MCP is on, even with zero
    # indexed views (returns an empty list rather than 404).
    try:
        tool(
            "search_all",
            (
                "Search every indexed model in the SmallStack site by free-text "
                "query. Returns ranked matches grouped across models. Use this "
                "when the user wants 'anything about X' without specifying which "
                "model. Per-model dedicated search_<plural> tools give the same "
                "results scoped to one model."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search text."},
                    "limit_per_model": {
                        "type": "integer",
                        "description": "Max results per indexed model (default 5).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            requires_access="readonly",
        )(_search_all_handler)
        count += 1
    except Exception:
        logger.exception("Failed to register search_all MCP tool")

    return count


async def _search_all_handler(args: dict):
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit_per_model") or 5)
    if not query:
        return {"results": []}
    hits = await sync_to_async(_search_all)(query, limit)
    return {"results": [h.as_dict() for h in hits]}


async def _search_help_handler(args: dict):
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit") or 10)
    if not query:
        return {"results": []}
    try:
        from apps.help.search import search_help_articles
    except Exception:
        return {"results": [], "error": "apps.help not installed"}
    hits = await sync_to_async(search_help_articles)(query, limit)
    return {"results": [h.as_dict() for h in hits]}


def _tool_name_for(view) -> str:
    """Match the per-view custom MCP noun if set, else fall back to plural."""
    custom = getattr(view.view_cls, "mcp_tool_noun_plural", None)
    if custom:
        return f"search_{custom}"
    plural = str(view.model._meta.verbose_name_plural).lower().replace(" ", "_")
    return f"search_{plural}"
