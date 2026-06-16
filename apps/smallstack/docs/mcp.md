# MCP (Model Context Protocol)

SmallStack ships an MCP server at `/mcp` so AI clients (Claude Desktop, Claude.ai Connectors, custom agents) can list, fetch, create, update, and delete records through the same form/queryset/permission logic your HTML and REST API already use.

## What's included

- `POST /mcp` and `POST /mcp/` — JSON-RPC 2.0 dispatch
- `GET /mcp` — friendly JSON banner for health checks
- Full OAuth 2.0 + PKCE surface (`/.well-known/oauth-authorization-server`, `/mcp/oauth/{register,authorize,token,revoke}`) for Claude.ai Connectors UI
- `enable_mcp = True` on any `CRUDView` auto-derives 1–5 MCP tools from it. Each `Action` in the view's `actions` (filtered by `mcp_actions` if set) becomes one tool — up to 5 per view (`list_`, `get_`, `create_`, `update_`, `delete_`).
- `@tool` decorator for adding curated cross-cutting tools that wrap aggregation or lookups an LLM would otherwise need many CRUD calls for
- Bearer-only auth (session cookies are deliberately rejected)
- `python manage.py mcp_doctor` for diagnostics (and `mcp_doctor --explain` to dump tool schemas — the same thing the LLM sees from `tools/list`)
- `make mcp-test` for an end-to-end HTTP smoke test against a running dev server (mint → tools/list → tools/call → revoke)
- **Admin pages at `/smallstack/mcp/`** — Health (mcp_doctor in HTML), Tools (browseable registry), Activity (recent /mcp requests). Staff-gated. See [`mcp-admin.md`](mcp-admin.md)
- **Dashboard widget** on `/smallstack/` — at-a-glance tool count + orphan-file health. Click → Health page.

## First connection (smoke test)

```bash
# 1. Mint a token
uv run python manage.py create_api_token admin --name "test" --access-level readonly

# 2. List tools
curl -s -X POST http://localhost:8005/mcp \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
```

If you haven't enabled MCP on any CRUDView yet, you'll get an empty list — that's still success.

## Enabling for a model

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_mcp = True
    mcp_description = "Tickets. Filter by status='open' to find unresolved work."
```

That gives you `list_tickets`, `get_ticket`, `create_ticket`, `update_ticket`, `delete_ticket` — wired through your existing `form_class`, `get_list_queryset` (for tenancy), `can_update` / `can_delete` (for row-level perms), and `on_form_valid` (for side effects).

See:
- [Your first MCP app in 10 minutes](mcp-first-app.md) — start here
- [Enable MCP for a CRUDView](mcp-enable-models.md)
- [Writing custom MCP tools](mcp-custom-tools.md)
- [Settings reference](mcp-settings.md) — every `MCP_*` setting documented
- [MCP authentication + OAuth](mcp-auth.md)
- [Architecture](mcp-architecture.md)
- [Admin pages + dashboard widget](mcp-admin.md)
- [Debugging](mcp-debugging.md)
- [Testing](mcp-testing.md)
- [Claude Desktop / Connectors UI](mcp-claude-desktop.md)
