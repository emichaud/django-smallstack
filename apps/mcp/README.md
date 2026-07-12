# mcp — Model Context Protocol server

The JSON-RPC MCP endpoint plus OAuth 2.0 + PKCE, and the `/smallstack/mcp/` admin (observer).
CRUDViews with `enable_mcp = True` become tools automatically; custom tools register via
`mcp_tools.py`.

**Status:** Framework-provided — don't edit in downstream forks; add tools via `mcp_tools.py`
in your own app.

**Key files:** `factory.py` (tool generation), `oauth_views.py`, `views.py` (runtime),
`admin/` (observer), `management/commands/mcp_doctor.py`. **URL:** `/mcp`, `/smallstack/mcp/`.

**See:** [`../../docs/skills/mcp/build-mcp-solution.md`](../../docs/skills/mcp/build-mcp-solution.md) ·
[`../../docs/skills/mcp/`](../../docs/skills/mcp/).
