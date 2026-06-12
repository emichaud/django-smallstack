# Debugging MCP

When Claude.ai's Connectors UI says "couldn't connect" or a tool call silently errors, start here.

## Step 1 — mcp_doctor

```bash
uv run python manage.py mcp_doctor
```

Checks: mcp package version, settings sanity, server registry contents, URL conf resolves, APIToken inventory, APITokenAdmin explorer_enabled, and (default) a live JSON-RPC self-test.

Flags:
- `--no-self-test` — skip the test-client request
- `--json` — machine-readable output for monitoring
- `--check-only` — exit 1 on any FAIL (useful in CI)

## Step 2 — log lines

Every request emits at least three lines under the `smallstack.mcp.views` logger:

```
MCP REQ ua=… accept=… has_auth=true body_len=…
MCP REQ method=tools/call id=42 params_keys=['name', 'arguments']
MCP RESP method=tools/call status=200 duration_ms=12.34
```

Tool execution:

```
MCP TOOL tool=list_tickets user_pk=7 duration_ms=8.1 result_len=312
MCP TOOL deny tool=update_ticket reason=readonly_blocked
MCP TOOL exception tool=… ... (full traceback)
```

OAuth:

```
OAUTH REGISTER client_id=mcp_abc redirect_uris=[…] client_name=…
OAUTH AUTHORIZE allowed user_pk=… client_id=… token_pk=… redirect_uri=claude.ai
OAUTH TOKEN issued user_pk=… token_pk=… scope=read
OAUTH TOKEN reject reason=pkce_mismatch client_id=…
```

Set `MCP_VERBOSE_LOGGING=True` to also dump request/response body previews at DEBUG.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Claude.ai says "not connected", logs show no requests | `initialize` returned an unsupported `protocolVersion` | Don't hardcode — `MCP_SUPPORTED_PROTOCOL_VERSIONS` already lists what we speak |
| `POST /mcp` returns 301 | Trailing-slash redirect ate the POST | Already mounted at both `/mcp` AND `/mcp/`; check `urls.py` didn't get reverted |
| Consent page submits but never returns to client | Site CSP `form-action 'self'` blocks the cross-origin redirect | `AuthorizeView` sets a per-response CSP allowing the redirect_uri origin — check it's not overridden |
| `tools/list` empty after `enable_mcp = True` | CRUDView never imported, so `__init_subclass__` never ran | Verify the app containing the CRUDView is in `INSTALLED_APPS` and its `urls.py` is included |
| 401 loop in Claude.ai | Token expired but `WWW-Authenticate` missing `resource_metadata` | All 401s carry the RFC 9728 header — if it's missing, an upstream middleware stripped it |
| `issuer_url` advertises `http://…` behind proxy | `request.is_secure()` is False in the WSGI worker | `oauth.issuer_url` already reads `HTTP_X_FORWARDED_PROTO` — make sure your proxy is setting it |

## Why MCP rejects session auth

`/mcp` requires Bearer even if you're logged in via Django session. Don't "fix" this — the upstream `mcp` SDK and Claude.ai both rely on stateless Bearer semantics. Session-based MCP would only work in-browser anyway.
