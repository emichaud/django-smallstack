# Skill: Debug an MCP failure

## When to use this skill
A client (Claude Desktop, Claude.ai, custom) is failing to attach to `/mcp` or a tool call is erroring.

## Decision tree

1. **No tools showing up at all** → `mcp_doctor`. If the registry shows 0 tools, no CRUDView has `enable_mcp = True` and `MCP_TOOL_MODULES` is empty.

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
