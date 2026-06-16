# Skill: Use the MCP admin pages

## When to use this skill
You're debugging or auditing an MCP setup in a project that has the admin pages installed (`/smallstack/mcp/` resolves). The user is browser-based, or you want to point them at a URL instead of a CLI command.

## What's there

Single sidebar entry **MCP** under Admin. Lands on Health. Internal tabs: Health / Tools / Activity.

| URL | Equivalent CLI | What it answers |
|---|---|---|
| `/smallstack/` (dashboard widget) | quick `mcp_doctor` summary | MCP status at a glance — green / amber |
| `/smallstack/mcp/` | `mcp_doctor` | Is MCP healthy right now? |
| `/smallstack/mcp/tools/` | `mcp_doctor --explain` | What tools can Claude see? |
| `/smallstack/mcp/tools/<name>/` | `mcp_doctor --explain <name>` | What does the schema for one tool look like? |
| `/smallstack/mcp/activity/` | `kamal app logs \| grep "/mcp"` | Did Claude actually call my tool yesterday? |
| `/smallstack/mcp/self-test/` (POST) | `mcp_doctor` self-test step | Does the in-process dispatcher work right now? |

All pages: `StaffRequiredMixin`. Anonymous → 302 login; non-staff → 403.

The dashboard widget is the cheapest signal — it's just a registry count + a cached orphan-file scan. Use it as the first-look "is anything off?" check before diving into the Health page.

## Debug flow — when to use which

1. **User reports "Claude isn't connecting"** → Health page. If any card is yellow or red, the detail tells you exactly which subsystem (package, settings, URLs, registry, tokens). Health WARN on the registry card means autodiscover missed a file — orphan paths are listed inline.

2. **User reports "Claude can call X but not Y"** → Tools page → click Y → look at `inputSchema`. The schema is exactly what `tools/list` returns. If a filter field is missing, add it to the CRUDView's `filter_fields`. If the description is the bare model name, set `mcp_description`.

3. **User reports "I added a tool last week but Claude never uses it"** → Tools page first (is it actually registered?). If yes, Activity tab → filter `since=7d` and `user=<them>` to see if Claude has called it. If Activity shows zero calls, the LLM doesn't know to use it — improve the `mcp_description`.

4. **User wants to verify a deploy** → Health page → "Run self-test now" button. The fragment swaps in inline; PASS with three sub-step ✓ means the dispatcher + auth + tool registry all work in-process. Combine with `make mcp-test` (different terminal) to also verify the real HTTP path.

## What the pages do NOT cover

- **Real HTTP reachability** — Health runs in-process. Use `make mcp-test` to exercise reverse proxy / middleware / network.
- **Per-tool argument capture** — Activity shows `path` and `status` but not which tool name was called or what arguments. Tail `smallstack.mcp.views` logger for that detail.
- **OAuth audit** — DCR registrations, code exchange success rate, etc. aren't surfaced here. Use the existing Explorer view on `OAuthAuthorizationCode` or grep `smallstack.mcp.oauth` logs.

## When NOT to recommend the admin pages

- The user is on a CI box without a browser — use `mcp_doctor --check-only` and `mcp_doctor --explain --json`.
- The user wants to script monitoring — the CLI's `--json` outputs are designed for that; the web pages are HTML.
- A test suite needs to assert behavior — write a `pytest` against `TOOL_REGISTRY` directly, not against the rendered pages.

## Don't

- Don't tell the user to "click the Run self-test button" if their app is deployed without `apps.activity` and they're debugging a reachability issue — the in-process self-test won't catch network problems. Use `make mcp-test` instead.
- Don't direct anonymous users to `/smallstack/mcp/` and call it "the public docs" — the pages 302 to login. The bundled help docs at `/smallstack/help/smallstack/mcp/` are the public reference.
- Don't try to write to `TOOL_REGISTRY` from the admin pages — the registry is populated at app-ready time from CRUDView attributes + `@tool` decorators. Edit the source of truth (the CRUDView class) and restart, not the browser.
