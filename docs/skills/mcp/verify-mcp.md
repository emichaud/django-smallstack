# Skill: Verify the MCP server works

## When to use this skill
You (or the user) need to confirm MCP is healthy / a tool is reachable / Claude can actually call something. There are multiple verify paths — this skill picks the right one for the question.

## The decision tree

| Question | Verify path | Cost |
|---|---|---|
| "Is the code wired correctly at all?" | `mcp_doctor` | <1s |
| "Will Claude see the schema I expect?" | `mcp_doctor --explain TOOL_NAME` | <1s |
| "Does the dispatcher work in-process?" | `mcp_doctor` self-test (default) | ~50ms |
| "Does HTTP+OAuth work end-to-end?" | `make mcp-test` | ~200ms |
| "Did Claude actually call this yesterday?" | `/smallstack/mcp/activity/?since=24h` | instant |
| "Is MCP healthy right now, browser-style?" | `/smallstack/mcp/` dashboard widget + Health page | instant |
| "Does the LLM actually use the tool when prompted?" | Connect Claude Desktop, ask in plain English | manual |
| "Will my pytest suite catch regressions?" | Add a tenancy/factory test | per-test |

## In order, when you're shipping new MCP work

### 1. After changing settings or code

```bash
uv run python manage.py check    # Django sanity
uv run python manage.py mcp_doctor    # MCP-specific
```

Look for:
- `[✓] mcp package` — dep is importable
- `[✓] Settings` — every `MCP_*` setting resolves
- `[✓] Server registry` — N tools registered (or WARN with orphan files)
- `[✓] URL conf` — all OAuth + JSON-RPC paths reachable

If registry says WARN with orphan files, fix that before continuing.

### 2. After adding a CRUDView opt-in or a `@tool`

```bash
mcp_doctor --explain                 # see every tool
mcp_doctor --explain my_new_tool     # detail one
```

Verify:
- The tool appears at all (if not → see `debug-mcp-failure.md`)
- The description reads like instructions the LLM can match against
- The `inputSchema` has every filter/argument you expect
- `write: True/False` matches your intent
- `requires_access` is right (None for read, `"staff"` for sensitive)

### 3. After wiring routes / middleware / proxy config

```bash
make run       # one terminal
make mcp-test  # another
```

`make mcp-test` exits:
- **0** — every step PASS (or SKIP if no tools registered)
- **2** — server unreachable (probably forgot `make run`)
- **4** — something returned non-200 or JSON-RPC error

This is the "did my proxy / WSGI / middleware actually serve `/mcp` correctly?" check. The in-process `mcp_doctor` can't catch reverse-proxy bugs because it uses Django's test client, not real sockets.

### 4. Browser sanity (staff-only)

Visit `/smallstack/` — the **MCP dashboard widget** appears next to Backups/Status with:
- `N tools` (green) — registry populated, no orphans
- `N tools` (amber) + "N unregistered files" — orphan WARN
- `No tools` (green) — empty registry, nothing wrong

Click through to `/smallstack/mcp/` for the full Health page. Tabs at the top:
- **Health** — color-coded `mcp_doctor` cards + "Run Self-Test" button
- **Tools** — browseable registry, click a tool → full schema + Copy curl
- **Activity** — recent `/mcp` requests filtered out of `RequestLog`

### 5. End-to-end LLM test

```bash
# Mint a real token first
uv run python manage.py create_api_token admin --name claude-dev --access-level readonly
```

In Claude Desktop → Settings → Connectors → Add custom connector:
- URL: `http://localhost:8005/mcp`
- Sign in, click Allow on the consent page

Then ask Claude something the LLM should be able to answer using your tools. If Claude picks the wrong tool or doesn't call any tool, your `mcp_description` strings need work — fix at the source, then re-test.

## Regression coverage — what's already tested

`apps/mcp/tests/` has 119 tests. The taxonomy:

| File | Covers |
|---|---|
| `test_admin_*.py` | Health / Tools / Activity / SelfTest views (auth gating + render) |
| `test_autodiscover.py` | `views.py` / `mcp_tools.py` get imported at startup |
| `test_dashboard_widget.py` | Widget state machine (empty / populated / orphans / API extras) |
| `test_dispatch.py` | JSON-RPC: initialize echo, ping, notifications 202+empty, etc. |
| `test_doctor.py` | All 6 `_check_*` methods + orphan detection + `--explain` |
| `test_factory.py` | CRUDView → tool emission, FK expansion, naming, per-action descriptions |
| `test_logging.py` | The promised log lines (REQ/RESP/AUTH/TOOL/OAUTH) |
| `test_oauth.py` | DCR, authorize, token exchange, revoke, RFC compliance |
| `test_pkce.py` + `test_x_forwarded_proto.py` | Compat edge cases |
| `test_session_login_rejected.py` | MCP is Bearer-only (no session auth) |
| `test_smoke.py` | `mcp_smoke` command (mint + tools/list + tools/call + revoke) |
| `test_tenancy.py` | `get_list_queryset(qs, request)` honored |
| `test_tool_decorator.py` | `@tool` registers + `current_context()` works |

When adding a new tool, follow patterns in `test_factory.py` (CRUDView) or `test_tool_decorator.py` (`@tool`).

## When verification fails

| Symptom | Most likely cause | Fix path |
|---|---|---|
| `mcp_doctor` registry WARN | Orphan `enable_mcp = True` files | Check `MCP_AUTODISCOVER`, or `from . import` in `AppConfig.ready()` |
| Tool exists but LLM doesn't use it | Description not descriptive enough | Improve `mcp_description` or `mcp_descriptions[Action.X]` |
| Tool returns wrong data | Tenancy filter missing | Add `qs.filter(owner=current_context().user)` in custom tools |
| `make mcp-test` exit 2 | Server not running | `make run` first |
| `make mcp-test` exit 4 | Real HTTP path broken (CORS, CSP, proxy) | Check Health page → log lines |
| Claude says "couldn't connect" | OAuth dance failure | Check `kamal app logs \| grep OAUTH` + `mcp-debugging.md` |

## Don't

- Don't write your own bash loops calling `/mcp` instead of `make mcp-test`. It's already a maintained smoke tester.
- Don't grep `kamal app logs` blindly — `/smallstack/mcp/activity/` filters to MCP traffic and is instant.
- Don't trust `mcp_doctor` PASS as proof of LLM correctness. The doctor verifies infrastructure; LLM correctness needs real Claude.
- Don't write integration tests that hit a real running server. Use Django's test client (see `test_dispatch.py` patterns) — keeps the suite fast.

## Related

- [`build-mcp-solution.md`](build-mcp-solution.md) — decide what to build
- [`debug-mcp-failure.md`](debug-mcp-failure.md) — diagnose specific failures
- [`mcp-admin-pages.md`](mcp-admin-pages.md) — the browser-first verify path
- [`connect-claude-desktop.md`](connect-claude-desktop.md) — Claude integration
- [`configure-mcp.md`](configure-mcp.md) — settings recipes
