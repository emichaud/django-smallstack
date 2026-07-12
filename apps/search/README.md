# search — full-text search + MCP search tools

Registry-driven keyword search over indexed CRUDViews, with pluggable backends (SQLite FTS5,
Postgres FTS, in-memory fallback) and access-tiered MCP search tools. Help articles are indexed
via a bridge.

**Status:** Framework-provided — don't edit in downstream forks; opt models in with
`enable_search`.

**Key files:** `registry.py`, `backends/`, `mcp_tools.py`, `signals.py`,
`management/commands/{rebuild_search_index,search_doctor,sync_help_index}.py`.

**See:** [`../../docs/skills/search.md`](../../docs/skills/search.md).
