# MCP admin pages

`mcp_doctor`, `mcp_doctor --explain`, and `make mcp-test` are great if you live in a terminal. The MCP admin pages give staff the same surfaces in a browser — useful when you're triaging from the phone or onboarding someone who doesn't run `manage.py`.

All three pages are gated by `StaffRequiredMixin`. Anonymous users get redirected to login; non-staff authenticated users get 403.

## Sidebar entry

A single **MCP** item under the admin section of the sidebar lands you on the Health page. From there, three tabs at the top of the page navigate between Health, Tools, and Activity.

## Dashboard widget

The `/smallstack/` dashboard surfaces an at-a-glance **MCP** card next to Backups and Help & Docs. It shows:

- `N tools` (green) — registry populated, no `enable_mcp = True` orphans
- `N tools` + "N unregistered files" (amber) — orphan WARN; some `enable_mcp` opt-in didn't make it to the registry
- `No tools` (green) — empty registry, no opt-ins anywhere; "awaiting `enable_mcp`"

Click → Health page. The widget is intentionally cheap (registry count + the cached orphan scan); it does NOT run the self-test on every dashboard load.

Also surfaced on the `/api/dashboard/widgets/` JSON endpoint with `tool_count`, `write_tool_count`, `read_tool_count`, and `orphan_count` for monitoring tools.

## Health (`/smallstack/mcp/`)

The same checks `mcp_doctor` prints, rendered as color-coded cards: mcp package presence, settings sanity, server registry contents (with orphan-file warnings if any), URL conf, APIToken inventory, APIToken admin Explorer integration.

At the top, a "Run self-test now" button. Clicking it mints a temp readonly token, runs `tools/list` + `ping` + `notifications/initialized` through Django's test client, revokes the token. Result swaps inline via htmx. The token cleanup runs in a `finally` so a Ctrl-C, browser close, or unexpected exception doesn't leave credentials behind.

This page does NOT exercise a real HTTP server — that's what `make mcp-test` is for. The Health checks run in-process, so they catch configuration/import issues that `manage.py check` misses, but won't surface reverse-proxy bugs or middleware misbehavior. Use both.

## Tools (`/smallstack/mcp/tools/`)

Browseable list of every registered MCP tool — exactly what `tools/list` returns over JSON-RPC. Columns: name, truncated description, write flag, required access level. Empty state when the registry is empty links to the `mcp-enable-models.md` skill so first-time admins land on the actionable path.

Click any tool name for the **detail page** (`/smallstack/mcp/tools/<name>/`):

- Full description (no truncation)
- Pretty-printed `inputSchema` — exactly what an MCP client sees
- Sample `curl` payload with a Copy button. Placeholder `<HOST>` + `<TOKEN>` because the page can't know what address external clients use or what token to insert

Unknown tool names return 404 immediately.

The same data is available from the CLI via `python manage.py mcp_doctor --explain` (or `--explain TOOL_NAME` for one), and that command remains the recommended path for scripting / CI gates. The web view is for browsing.

## Activity (`/smallstack/mcp/activity/`)

Recent `/mcp` HTTP requests captured by `apps.activity.RequestLog`. Default window is the last 24 hours. Filter form supports method (any/GET/POST), status class (any/2xx/4xx/5xx), time window (24h/7d/all), and a username icontains match. Pagination at 50 per page.

If `apps.activity` isn't in `INSTALLED_APPS`, the page shows a banner instead of crashing.

Status badges are color-coded the same way Health is: 2xx green, 3xx neutral, 4xx amber, 5xx red. The MCP-specific data — which tool was called, what arguments were passed, what was returned — isn't in RequestLog; if you need that level of detail, watch the `smallstack.mcp.views` logger and consider a dedicated `MCPCall` model (currently deferred).

## When to use each tool

| Question | Best surface |
|---|---|
| Is MCP healthy right now? | Health page (or `mcp_doctor`) |
| What tools can Claude see? | Tools page (or `mcp_doctor --explain`) |
| Did Claude actually call `list_tickets` yesterday? | Activity page |
| Is the dispatcher reachable from the real internet? | `make mcp-test` |
| Is my CRUDView correctly opted in? | Health → orphan warning, then Tools page |
| What inputSchema does the LLM see for tool X? | Tools → click X (or `mcp_doctor --explain X`) |

## Related

- [`mcp.md`](mcp.md) — overview
- [`mcp-debugging.md`](mcp-debugging.md) — symptom → cause table
- [`mcp-enable-models.md`](mcp-enable-models.md) — three-line opt-in for a CRUDView
- `make mcp-test`, `make mcp-doctor` — the CLI equivalents
