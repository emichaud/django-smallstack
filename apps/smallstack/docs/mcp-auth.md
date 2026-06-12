# MCP authentication

MCP requires a Bearer token. Session cookies are deliberately rejected — the protocol is bearer-only.

## Two ways to mint a token

### Manual (curl, scripts, CI)

```bash
uv run python manage.py create_api_token \
  --user alice \
  --name "CI runner" \
  --access-level readonly
```

`--access-level` is one of `readonly` / `staff` / `auth`. Raw key is printed once.

### OAuth (Claude Desktop / Claude.ai Connectors UI)

Fully automatic. The flow:

1. Client calls `POST /mcp/oauth/register` (RFC 7591 DCR) → gets a `mcp_…` client_id
2. Client redirects user to `GET /mcp/oauth/authorize?client_id=…&redirect_uri=…&code_challenge=…&code_challenge_method=S256&state=…`
3. User signs in (Django session) → consent page (`apps/mcp/templates/mcp/authorize.html`)
4. User clicks Allow → server mints `APIToken(name="MCP — <client_id>", access_level=readonly)`, writes a one-shot `OAuthAuthorizationCode` row, 302s back with `?code=…&state=…`
5. Client calls `POST /mcp/oauth/token` with the code + PKCE verifier → gets the bearer

PKCE is S256-only. `plain` is rejected.

## Access levels

| Level | Read tools | Write tools | Staff-mixin tools |
|---|---|---|---|
| `readonly` | yes | **no** | no |
| `staff` | yes | yes | yes if user `is_staff` |
| `auth` | yes | yes | yes if user `is_staff` |

`write=True` on a `@tool` (or any factory-emitted create/update/delete) rejects `readonly` tokens with RPC -32600 / HTTP 403.

## Token management

`APIToken` is registered with `explorer_enabled = True` so non-superuser staff can browse, audit, and revoke tokens from Explorer under **Auth → API tokens**. The OAuth consent page links to this page so users know where to revoke later.

## RFC discovery

- `/.well-known/oauth-authorization-server` — RFC 8414
- `/.well-known/oauth-protected-resource` — RFC 9728 (`resource` deliberately has no trailing slash to match Claude.ai's literal comparison)
- `/mcp/oauth/register` — RFC 7591 (stateless; PKCE binds everything at /authorize)
- `/mcp/oauth/revoke` — RFC 7009 (soft-revoke; 200 even for unknown tokens to avoid enumeration)

## 401 + WWW-Authenticate

`POST /mcp` without a Bearer returns HTTP 401 with:

```
WWW-Authenticate: Bearer realm="mcp", error="invalid_token", resource_metadata="https://host/.well-known/oauth-protected-resource"
```

Per RFC 9728. Stale-token clients use this to discover where to start re-auth.
