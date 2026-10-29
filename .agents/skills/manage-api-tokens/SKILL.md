---
name: manage-api-tokens
description: "Pick the right token surface (/smallstack/tokens/, CLI, OAuth) by question; permissions matrix; reveal-once flow"
license: MIT
metadata:
  source: "docs/skills/manage-api-tokens.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/manage-api-tokens.md` by `make skills-index` — edit the source, not this file.

# Skill: Manage API tokens through the web UI

## When to use this skill
The user mentions API tokens, Bearer tokens, "my Claude token", or wants to mint / revoke / inspect a token. You need to decide which surface to point them at.

## Surface chooser

| Question / Task | Use |
|---|---|
| "Where do I see my tokens?" | `/smallstack/tokens/` (works for any logged-in user) |
| "Mint a token for Claude / my script / CI" | `/smallstack/tokens/create/` |
| "Revoke a leaked / old token" | Detail page → "Revoke" action |
| "What's used this token in the last day?" | Detail page → Usage panel |
| "Audit all tokens on the system" | Staff: `/smallstack/tokens/` (shows all); or `/explorer/auth/apitoken/` |
| Scripted mint (CI / Makefile / .env build) | `manage.py create_api_token <username> --access-level readonly` |
| OAuth flow from Claude Desktop | `/mcp/oauth/authorize` (consent page) — token shows up in `/smallstack/tokens/` after |
| Direct REST mint with username/password | `POST /api/auth/token/` |

## Permissions cheat sheet

When recommending an action, check what the user's role can actually do:

- **Anonymous** → recommend login first
- **Authenticated (non-staff)** → mint **readonly** for **self** only; can revoke own tokens
- **Staff** → mint **readonly** or **staff** for any user; can revoke any token
- **Superuser** → mint **any** access level (`readonly` / `staff` / `auth`) for any user

If they ask to mint a write-capable token but aren't staff, tell them they need staff escalation — don't try to work around the form.

## The reveal flow — explain this

The raw token key is shown **exactly once** at mint time, on the reveal page (`/smallstack/tokens/<pk>/reveal/`). It's stashed in their session as a one-shot.

If they:
- **Refresh** the reveal page → key is gone (session popped), they see "Token key is no longer available."
- **Navigate away** without copying → key is gone forever; only the hash is in the DB.

Tell them up front: "Copy the key now. The page will only show it once."

Don't suggest workarounds like fetching the hash and reversing — it can't be done; that's the point.

## Common debugging requests

### "My Claude token doesn't work"

1. Visit `/smallstack/tokens/` — is the token there?
2. Is it `active`? (Look for the badge in the status column.)
3. Click it — is the `access_level` correct for what they're trying to do? (`readonly` can't POST.)
4. Usage panel: do recent requests show up? If yes, the token works; their client is sending it wrong.

### "I think I leaked a token"

Visit `/smallstack/tokens/`, find it (search by name or prefix), click in, hit Revoke. The token is soft-deleted (`is_active=False`, `revoked_at=<now>`). Any client using it starts getting 401s immediately. Then mint a fresh one.

### "How do I do this from a script / CI?"

`manage.py create_api_token <username> --access-level readonly --name "ci-runner"` prints the raw key. Capture it into an env var. Don't use the web UI for scripted minting.

### "I want to know what called this token"

If `apps.activity` is installed, the token detail page's Usage panel shows the last 24h. For longer windows, use `/smallstack/activity/?api_token=<pk>` (when implemented) or filter `RequestLog.objects.filter(api_token=token)` in shell.

## Don't

- Don't tell users to "look in `/admin/`" unless they're a superuser. Django admin shows the model but not the token-flow UX.
- Don't recommend `/explorer/auth/apitoken/` to non-staff. It's staff-gated; they'll hit 403.
- Don't write tools that re-implement the token-mint logic. `APIToken.create_token(...)` and the `/api/auth/token/` flow already do the right thing (hashing, prefix, last_used tracking).
- Don't make the user log out / back in to "refresh" a token. Tokens are independent of session cookies; revoking + re-minting is the only path.

## Related

- [`apps/smallstack/docs/api-tokens.md`](../../apps/smallstack/docs/api-tokens.md) — full reference
- [`mcp/connect-claude-desktop.md`](mcp/connect-claude-desktop.md) — OAuth-minted tokens
- [`mcp/configure-mcp.md`](mcp/configure-mcp.md) — when to disable OAuth-minting entirely
