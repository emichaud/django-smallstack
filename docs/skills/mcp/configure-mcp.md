# Skill: Configure MCP for the use case at hand

## When to use this skill
The user wants to change MCP's behavior — turn OAuth on/off, switch to a different theme, deploy behind a proxy, harden for prod, etc. — and you need to know which setting to touch (and which NOT to touch).

For the comprehensive setting-by-setting reference, see [`apps/smallstack/docs/mcp-settings.md`](../../apps/smallstack/docs/mcp-settings.md). This skill picks the right setting for common scenarios.

## Scenario → setting map

### "I want to disable OAuth completely (internal-only deploy)"

```python
# config/settings/smallstack.py
MCP_ENABLE_OAUTH = False
```

OR via env:
```bash
MCP_ENABLE_OAUTH=false
```

What it does: Disables Claude.ai Connectors UI integration. Manual `manage.py create_api_token` and direct Bearer auth still work. The `/.well-known/oauth-*` endpoints stay on (some clients probe them) but `/mcp/oauth/*` endpoints become orphaned.

When NOT to use this: If you want any Claude.ai user to connect with one click — keep it `True`.

### "I want the consent page to match my custom theme"

```python
MCP_BASE_TEMPLATE = "yourtheme/base.html"
```

The OAuth consent page (`apps/mcp/templates/mcp/authorize.html`) extends this template. As long as your base provides the standard SmallStack CSS vars (`--primary`, `--card-bg`, etc.), the page picks up your theme automatically.

To override the consent HTML itself, place a `templates/mcp/authorize.html` in your project — Django's template loader picks the project copy first.

### "I'm deploying behind kamal-proxy / nginx / ALB"

**No setting change needed.** `oauth.issuer_url(request)` already reads `HTTP_X_FORWARDED_PROTO` so the OAuth metadata advertises `https://` correctly.

Verify by curling the discovery endpoint from inside the running container:

```bash
curl -s https://your-prod-host/.well-known/oauth-authorization-server | jq .issuer
# should print: "https://your-prod-host"
```

If it shows `http://`, your proxy isn't forwarding the header. Fix at the proxy, not in MCP.

### "I want to debug a specific MCP request flow"

```bash
MCP_VERBOSE_LOGGING=true uv run python manage.py runserver 8005
```

Adds DEBUG-level lines with truncated request/response bodies (1 KB cap each direction) to the `smallstack.mcp.views` logger. Watch via `tail -f` or just the runserver console.

**Don't leave on in production** — request bodies contain user data.

### "I want to expose `@tool`s in a custom module location"

If you put `@tool`-decorated functions in something other than `<app>/views.py` or `<app>/mcp_tools.py`, autodiscover won't find them. Two options:

```python
# Option A — list each module explicitly
MCP_TOOL_MODULES = [
    "apps.support.custom_mcp_tools",
    "apps.billing.ai_helpers",
]
```

```python
# Option B — import from your AppConfig.ready()
class SupportConfig(AppConfig):
    name = "apps.support"
    def ready(self):
        from . import custom_mcp_tools  # noqa: F401
```

Either works. `MCP_TOOL_MODULES` is the more discoverable option — anyone reading settings can see the surface.

### "I'm hitting circular-import errors from autodiscover"

```python
MCP_AUTODISCOVER = False
```

Then every CRUDView with `enable_mcp = True` needs an explicit import from its app's `ready()`:

```python
class MyAppConfig(AppConfig):
    name = "apps.myapp"
    def ready(self):
        from . import views  # noqa: F401  — registers MCP CRUDViews
```

And every `@tool` module needs to be listed in `MCP_TOOL_MODULES`. `mcp_doctor` will WARN with orphan-file paths if you forget any.

### "I want multi-tenant token tagging"

```python
import os
MCP_SERVER_NAME = f"smallstack-{os.getenv('TENANT', 'main')}"
MCP_TOKEN_NAME_PREFIX = f"MCP-{os.getenv('ENV', 'prod')}"
```

OAuth-minted tokens are named `"MCP-prod — mcp_aB3xyz"` etc., so you can grep / filter by environment in Explorer / shell.

### "I want to pin to a known-good protocol version during a Claude.ai upgrade"

```python
MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2025-03-26", "2024-11-05"]
```

Removes `2025-06-18` from the supported list. The dispatcher's negotiation will return `2025-03-26` to any client that asks for it (or `2024-11-05` if the client wants something even older).

Be careful: removing the most-recent version may break new clients. Re-add when stable.

### "I want a stricter OAuth code TTL for security audits"

```python
MCP_OAUTH_CODE_TTL_SECONDS = 300  # 5 minutes instead of 10
```

Default 600 is standard. Don't go below 60s — slow networks and laggy consent UIs will eat the budget.

### "I want to add a custom name prefix to MCP-minted tokens"

```python
MCP_TOKEN_NAME_PREFIX = "ClaudeMCP"
```

Tokens become `"ClaudeMCP — mcp_xxx"`. Helps when you have multiple token-mint pathways (CI, manual, OAuth) and want to filter.

## What NOT to touch

| Setting | Reason |
|---|---|
| Hardcode `MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05"]` (only) | Older clients work; newer clients silently disconnect when their version isn't echoed back |
| Loosen `MCP_OAUTH_CODE_TTL_SECONDS` above 900 | Long-lived codes are a credential-theft window |
| Remove `apps.mcp` from `INSTALLED_APPS` to "turn off MCP" | The OAuthAuthorizationCode model needs migrations; just `MCP_ENABLE_OAUTH=False` instead |
| Set `MCP_VERBOSE_LOGGING=True` in production | Request bodies contain user data |
| Override `apps/mcp/views.py:McpHttpView` | Compatibility quirks (trailing slash, protocolVersion echo, WWW-Authenticate) are baked in for a reason |

## Verify after configuring

```bash
uv run python manage.py mcp_doctor
# → Settings card should show your overrides applied
# → Other checks still PASS

make mcp-test
# → Confirms HTTP path still works with the new config
```

If `mcp_doctor` shows your override but `make mcp-test` fails, your config is doing what you asked but something else broke — see [`debug-mcp-failure.md`](debug-mcp-failure.md).

## Don't

- Don't change settings in production without first verifying in dev. MCP settings affect both the OAuth discovery surface and the dispatcher's protocol handling — easy to break Claude integration silently.
- Don't override settings inside Python code. Use env vars + `.env` so the same code path works locally and in production.
- Don't enable `MCP_VERBOSE_LOGGING` permanently. It belongs in debug sessions.
- Don't disable `MCP_AUTODISCOVER` "to be safe". It exists for a reason (the silent zero-tools footgun); disabling means every new CRUDView needs manual hookup or `mcp_doctor` WARN.

## Related

- [`apps/smallstack/docs/mcp-settings.md`](../../apps/smallstack/docs/mcp-settings.md) — every setting in detail
- [`add-mcp-to-this-project.md`](add-mcp-to-this-project.md) — bootstrap from zero
- [`debug-mcp-failure.md`](debug-mcp-failure.md) — when something breaks after config
- [`verify-mcp.md`](verify-mcp.md) — confirm changes took effect
