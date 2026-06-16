# Skill: Debug an MCP failure

## When to use this skill
A client (Claude Desktop, Claude.ai, custom) is failing to attach to `/mcp` or a tool call is erroring.

## Decision tree

0. **Prefer clicking?** If `/smallstack/mcp/` resolves on this project, every check below has a browser surface — Health page mirrors `mcp_doctor`, Tools page mirrors `--explain`, Activity page filters request history. See [`mcp-admin-pages.md`](mcp-admin-pages.md) for the page → answer mapping.

1. **No tools showing up at all** → `mcp_doctor`. If the registry shows 0 tools, no CRUDView has `enable_mcp = True` and `MCP_TOOL_MODULES` is empty. If the doctor WARNs that `enable_mcp = True` files aren't represented in the registry, the named file's CRUDView isn't being imported — either `MCP_AUTODISCOVER` is off, or the CRUDView lives outside `views.py`/`mcp_tools.py` and the owning app's `AppConfig.ready()` isn't importing it.

   **The LLM sees the wrong tool list or wrong schema?** → `mcp_doctor --explain` dumps every registered tool's description + `inputSchema`. Use `--explain TOOL_NAME` for one tool; pipe `--explain --json` through `jq` for surgical queries like "which tools take a `status` parameter?". Typical findings:
   - Schema is missing a filter the user expects → add the field to `filter_fields` on the CRUDView.
   - Description is the bare model name → set `mcp_description` to a sentence the LLM can match against.
   - Read tool incorrectly marked `write: True` (or vice-versa) → check the decorator / `Action` mapping.

   **Doctor passes but real HTTP calls fail?** → `make mcp-test` runs the same mint → tools/list → tools/call → revoke loop against a live server (not the in-process test client). Catches reverse-proxy bugs, port collisions, header-stripping middleware, and CSP changes that wouldn't show up in the doctor's in-process self-test. Exits 2 on connection failure, 4 on JSON-RPC error.

2. **Client says "couldn't connect", no log lines** → the GET banner is reachable, but POST isn't. Three usual causes:
   - APPEND_SLASH redirected POST to GET. Both `/mcp` and `/mcp/` must accept POST. Check `apps/mcp/urls.py` — it should mount the same view twice.
   - Bad `protocolVersion` on `initialize`. Check `MCP_SUPPORTED_PROTOCOL_VERSIONS` is populated; the dispatcher echoes the client's value if supported, else falls back to the first entry.
   - 401 missing `WWW-Authenticate`. Every 401 must include `Bearer realm="mcp", error="invalid_token", resource_metadata="…"`.

3. **OAuth consent page hangs after Allow** → site-wide CSP `form-action 'self'` blocks the cross-origin redirect to Claude.ai's callback. `AuthorizeView._add_csp_for_redirect` already overrides this per-response — verify no upstream middleware is restoring the stricter header.

4. **`tools/call` returns -32603 with traceback** → check `smallstack.mcp.views` ERROR lines. Most often: tool tried to read from `request` (use `current_context()`) or returned a non-JSON-serializable value (call `list(qs)` or serialize manually).

5. **`tools/call` returns 403 / "Forbidden: readonly_blocked"** → the tool is `write=True` and the token is readonly. Mint a staff token or remove `write=True` if the tool is actually read-only.

6. **`tools/call` returns "Forbidden: staff_required"** → CRUDView has `StaffRequiredMixin` and `token.user.is_staff` is False. Wrong user, or token belongs to a non-staff user.

7. **`issuer_url` advertises `http://` behind kamal-proxy** → `request.is_secure()` returns False inside the WSGI worker; the proxy isn't forwarding `X-Forwarded-Proto`. Check kamal config.

## Log patterns to grep for

```bash
kamal app logs | grep -E "smallstack\.mcp\.(views|oauth|auth|factory)"
```

- `MCP REQ method=…` — request arrived
- `MCP RESP method=… status=… duration_ms=…` — request finished
- `MCP AUTH failed reason=…` — bearer-related rejection
- `MCP TOOL deny tool=… reason=…` — access check rejected a call
- `MCP TOOL exception tool=…` — handler raised; traceback follows
- `OAUTH TOKEN reject reason=pkce_mismatch` — PKCE verification failed (wrong verifier or stale code)

## Enable verbose logging when stuck

```bash
MCP_VERBOSE_LOGGING=true uv run python manage.py runserver 8005
```

DEBUG-level lines include truncated request/response bodies.

## Don't

- Don't "fix" 401 on session-only requests. MCP is bearer-only by design.
- Don't add the request body to logs at INFO. The verbose mode exists for a reason — bodies can contain user data.
