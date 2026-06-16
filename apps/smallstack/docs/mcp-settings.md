# MCP settings reference

Every Django setting that affects the MCP server. All settings have safe defaults — you only need to touch them when you're tuning for production, a non-standard deploy, or a downstream theme.

All settings are declared in `config/settings/smallstack.py` and read via `python-decouple`'s `config()` helper, so any of them can be overridden by an environment variable (or `.env` entry) of the same name.

## Quick reference

| Setting | Default | What it does |
|---|---|---|
| `MCP_SERVER_NAME` | `BRAND_NAME.lower()` | Server name advertised on `initialize` + GET banner |
| `MCP_SERVER_VERSION` | `"1.0.0"` | Version string on `initialize` |
| `MCP_BASE_TEMPLATE` | `"website/base.html"` | Base template the OAuth consent page extends |
| `MCP_TOKEN_NAME_PREFIX` | `"MCP"` | Prefix for OAuth-minted APIToken names |
| `MCP_SUPPORTED_PROTOCOL_VERSIONS` | `["2025-06-18", "2025-03-26", "2024-11-05"]` | Protocol versions the dispatcher can speak |
| `MCP_OAUTH_CODE_TTL_SECONDS` | `600` | How long an OAuth authorization code is valid |
| `MCP_ENABLE_OAUTH` | `True` | Enable the OAuth flow for AI clients |
| `MCP_VERBOSE_LOGGING` | `False` | Log request/response body previews at DEBUG |
| `MCP_TOOL_MODULES` | `[]` | Modules to import at startup (for `@tool` registration) |
| `MCP_AUTODISCOVER` | `True` | Auto-import every app's `views.py` + `mcp_tools.py` |

---

## Setting-by-setting

### `MCP_SERVER_NAME`

The string MCP clients see in the `initialize` response under `serverInfo.name`, and on the friendly GET `/mcp` banner. Defaults to a slug of `BRAND_NAME` — e.g. `"smallstack"` for the upstream, `"opshugger"` for OpsHugger.

**When to change:** Multi-tenant deployments where you want each tenant's MCP server identifiable by name. Or marketing/branding alignment.

```python
MCP_SERVER_NAME = "smallstack-staging"
```

### `MCP_SERVER_VERSION`

Version string in `initialize`. Doesn't affect protocol negotiation — that's `MCP_SUPPORTED_PROTOCOL_VERSIONS`.

**When to change:** Bumping with releases is a good practice. Some monitoring tools key off this.

### `MCP_BASE_TEMPLATE`

The Django template `apps/mcp/templates/mcp/authorize.html` extends. Default `"website/base.html"` is the SmallStack generic base. The consent page inherits the site's nav, theme, and CSS variables, so the OAuth consent UI naturally matches the rest of the project.

**When to change:** Themed downstream projects (smallstack-tabler etc.) override to their own base template. Pure API deployments with no website base can set this to a minimal template.

```python
# In smallstack-tabler's smallstack.py
MCP_BASE_TEMPLATE = "tabler/base.html"
```

### `MCP_TOKEN_NAME_PREFIX`

When the OAuth flow mints an APIToken on a successful Authorize, the token's `name` field becomes `f"{MCP_TOKEN_NAME_PREFIX} — {client_id}"`. So an OAuth grant to Claude Desktop yields a token named `"MCP — mcp_aB3xyz9"`.

**When to change:** Multi-environment setups where you want to distinguish tokens minted from different MCP servers (`"MCP-prod"` vs `"MCP-staging"`).

### `MCP_SUPPORTED_PROTOCOL_VERSIONS`

List of MCP protocol versions the dispatcher knows how to speak, **most-recent first**. On `initialize`, the dispatcher echoes the client's `protocolVersion` if it appears in this list; otherwise it falls back to the first entry. Hardcoding a single version (or omitting newer ones) causes Claude.ai to silently disconnect.

**When to change:** Pinning to a known-good version while a new spec is in flux. Removing versions is risky — old clients may break.

```python
# Conservative pin during a spec migration
MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2025-03-26", "2024-11-05"]
```

### `MCP_OAUTH_CODE_TTL_SECONDS`

How long an OAuth authorization code (`/mcp/oauth/authorize` → 302 → code) is valid before the user must restart the flow. Default 600 (10 minutes) follows OAuth common practice.

**When to change:** Mostly fine as-is. Tightening to 300 is defensible for higher-security setups. Loosening above 900 is bad — long-lived codes are a credential-theft hazard.

### `MCP_ENABLE_OAUTH`

Master switch for the OAuth surface. When `False`:
- All `/mcp/oauth/*` endpoints still resolve but should be considered unused
- The `/.well-known/oauth-*` discovery endpoints stay on (necessary if some clients probe them)
- Tokens still work via the manual `manage.py create_api_token` path

**When to change:**
- **Internal-only deployments** behind a VPN where you mint all tokens by hand and don't want Claude.ai connecting at all → `False`.
- **Production where you want both** OAuth (for end-users) and manual tokens (for CI / scripts) → keep `True`.

### `MCP_VERBOSE_LOGGING`

When `True`, the `smallstack.mcp.views` logger emits DEBUG-level lines including truncated request/response bodies (1 KB each direction). Otherwise only INFO-level metadata logs (method, status, duration).

**When to change:** Temporarily during a debug session. Set via env so you can flip without redeploying:

```bash
MCP_VERBOSE_LOGGING=true uv run python manage.py runserver 8005
```

Don't leave on in production — bodies can contain user data.

### `MCP_TOOL_MODULES`

List of Python module paths the MCP app imports at startup so any `@tool` decorators inside them self-register. Empty by default.

**When to change:** Whenever you add cross-cutting `@tool` functions in modules NOT auto-discovered by `MCP_AUTODISCOVER`.

```python
MCP_TOOL_MODULES = [
    "apps.mcp_tools.ticket_summary",
    "apps.mcp_tools.find_anything",
]
```

`@tool`s defined inside `<app>/views.py` or `<app>/mcp_tools.py` are picked up by autodiscover automatically — no listing needed.

### `MCP_AUTODISCOVER`

When `True` (default), `apps.mcp.AppConfig.ready()` walks every installed app and tries `importlib.import_module("<app>.views")` + `importlib.import_module("<app>.mcp_tools")`. This is what makes `enable_mcp = True` on a CRUDView "just work" — without autodiscover, Django wouldn't import `views.py` until URL resolution and the registry would be empty when `ready()` walked it.

**When to change:**
- **Set `False` if you hit circular-import issues** in a downstream project. Then list every CRUDView module in `MCP_TOOL_MODULES` or add explicit `from . import views` to each app's `AppConfig.ready()`.

```bash
MCP_AUTODISCOVER=false
```

If you flip this and the registry goes empty, `mcp_doctor` will WARN with the orphan-file list so you know exactly which files need an explicit import.

---

## Common configurations

### Internal-only deployment (manual tokens only)

```python
MCP_ENABLE_OAUTH = False
MCP_VERBOSE_LOGGING = False  # keep prod quiet
```

OAuth endpoints are still mounted but unused. Mint tokens with `manage.py create_api_token` for CI / scripts / known users.

### Production behind kamal-proxy / nginx

No settings change needed — `oauth.issuer_url()` reads `HTTP_X_FORWARDED_PROTO` first so the advertised issuer URL stays on `https://`. Verify by hitting `/.well-known/oauth-authorization-server` and confirming `issuer` starts with `https://`.

### Debug session for "Claude says it can't connect"

```bash
# In one terminal
MCP_VERBOSE_LOGGING=true uv run python manage.py runserver 8005

# In another, watch the structured logs
tail -f logs/django.log | grep "smallstack.mcp"
```

### Downstream project with custom theme

```python
# config/settings/smallstack.py — your project's overlay
MCP_BASE_TEMPLATE = "your_theme/base.html"
MCP_SERVER_NAME = "your-product-name"
```

The OAuth consent page picks up your theme automatically.

### Multi-tenant / multi-environment

```python
import os
MCP_SERVER_NAME = f"smallstack-{os.getenv('TENANT', 'main')}"
MCP_TOKEN_NAME_PREFIX = f"MCP-{os.getenv('ENV', 'prod')}"
```

Each tenant's tokens are visibly tagged in `manage.py shell` / Explorer.

### Pure-internal MCP behind a fully-trusted VPN

```python
MCP_ENABLE_OAUTH = False
MCP_VERBOSE_LOGGING = False
# Optional: tighten the protocol list to a stable version
MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05"]
```

---

## Related

- [`mcp.md`](mcp.md) — overview
- [`mcp-first-app.md`](mcp-first-app.md) — linear walkthrough
- [`mcp-enable-models.md`](mcp-enable-models.md) — opt a CRUDView in
- [`mcp-auth.md`](mcp-auth.md) — APIToken lifecycle, OAuth flow
- [`mcp-debugging.md`](mcp-debugging.md) — `mcp_doctor`, log lines
