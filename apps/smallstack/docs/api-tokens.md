# API tokens — self-service management

SmallStack ships a token management UI at **`/smallstack/tokens/`**. Any authenticated user can list, mint, view, and revoke their own API tokens. Seeing every account's tokens needs a staff account holding `smallstack.view_apitoken` (the *Token manager* group); other staff see their own, as everyone does. Revoking someone else's needs `smallstack.change_apitoken` (the *Token manager* group), and only a superuser revokes a superuser's. The page sits in the sidebar as **API Tokens** next to MCP and Backups.

This complements the existing surfaces:

| Surface | Audience | Purpose |
|---|---|---|
| `/smallstack/tokens/` | Any authenticated user (this page) | Self-service mint / view / revoke for your own tokens |
| `/explorer/auth/apitoken/` | Staff only | Cross-user audit / bulk operations |
| Django admin `/admin/smallstack/apitoken/` | Superusers | Schema-level edits |
| `manage.py create_api_token` | CLI / scripts | Scripted mint (e.g. CI) |
| `POST /api/auth/token/` | Programmatic | Mint via REST (basic-auth → token) |
| `POST /mcp/oauth/token` | OAuth clients | OAuth-minted tokens (Claude Desktop / Connectors UI) |

All surfaces store into the same `APIToken` model. A token minted by any path can be managed from any other.

## Permissions

| Role | List | Mint | Revoke |
|---|---|---|---|
| Anonymous | redirect to login | — | — |
| Authenticated (non-staff) | own tokens only | own user, `readonly` access level only | own tokens only |
| Staff | own tokens; all with `view_apitoken` | self, or (with `add_apitoken`) a narrower account; `readonly` or `staff` levels | own; others' with `change_apitoken` |
| Superuser | all tokens | self or other; any access level (`auth`/`staff`/`readonly`) | any token |

Non-staff users see a hidden user picker pre-filled with themselves, and only `readonly` in the access-level dropdown. Staff users see the full picker and `readonly` + `staff`. Superusers additionally see `auth`.

## The reveal flow

A raw token key is generated at mint time and immediately hashed for storage. The raw key is **never persisted** — only its SHA-256 hash and an 8-character prefix.

To make the key usable, the mint flow:

1. Creates the row + hash on POST to `/smallstack/tokens/create/`.
2. Stashes the raw key in `request.session` under a one-shot key.
3. Redirects to `/smallstack/tokens/<pk>/reveal/`.
4. Reveal page reads the session, displays the key with a Copy button, and **pops** the session entry so a refresh sees `None`.
5. Refreshing reveal after the pop redirects to the list with a "key is no longer available" message.

If a user navigates away from the reveal page without copying, the key is gone. They have to mint a new token. This is intentional — short-circuiting the one-shot pattern would let attackers replay reveal URLs.

## Stats panel

Each token's detail page (`/smallstack/tokens/<pk>/`) shows a 24-hour usage breakdown when `apps.activity` is installed: total requests, average response time, and per-status-code counts. The numbers come from `RequestLog.objects.filter(api_token=token, timestamp__gte=...)`.

If `apps.activity` isn't installed, the panel shows zeros and a graceful note rather than crashing.

## Dashboard widget

`/smallstack/` shows an **API Tokens** card with:

- `N active` headline
- `of M total (K revoked)` detail
- `operational` status — drives the headline color

The widget is cheap (two COUNT queries) so it doesn't slow the dashboard. The companion `/api/dashboard/widgets/` JSON endpoint includes structured extras: `total_tokens`, `active_tokens`, `revoked_tokens`, `by_access_level: {readonly, staff, auth}`.

## MCP integration

The OAuth consent page at `/mcp/oauth/authorize` deep-links to `/smallstack/tokens/` for post-grant management. When a user signs in to Claude Desktop and clicks Allow, the resulting token shows up here within 1 second of the OAuth dance completing. They can revoke it from this UI any time.

If a downstream project doesn't install `apps.tokenmgr`, MCP falls back to `/explorer/auth/apitoken/` (staff-only). The consent page link still resolves; only the audience is narrower.

## CLI minting

`manage.py create_api_token` stays the canonical scripted path:

```bash
uv run python manage.py create_api_token alice --name "CI" --access-level readonly
```

The web UI is for interactive use; the CLI is for `Makefile` / cron / deploy scripts. Both share the same `APIToken.create_token` factory.

## Related

- [`mcp-auth.md`](mcp-auth.md) — APIToken lifecycle in the MCP context
- [`mcp-admin.md`](mcp-admin.md) — `/smallstack/mcp/` admin pages
- [`authentication.md`](authentication.md) — broader auth model
