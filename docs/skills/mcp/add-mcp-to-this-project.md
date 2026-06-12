# Skill: Add MCP to a project that doesn't have it yet

## When to use this skill
You're working in a derived SmallStack project that hasn't pulled the MCP upstream yet, or you're adding MCP to a fresh fork.

## Steps

1. Ensure `mcp>=1.27` is in `pyproject.toml` dependencies. Run `uv sync`.

2. Add `apps.mcp` to `INSTALLED_APPS` in `config/settings/base.py`:

   ```python
   INSTALLED_APPS = [
       # ...
       "apps.website",
       "apps.mcp",
       # ...
   ]
   ```

3. Add the MCP settings block to `config/settings/smallstack.py`:

   ```python
   MCP_SERVER_NAME = config("MCP_SERVER_NAME", default=BRAND_NAME.lower().replace(" ", "-"))
   MCP_SERVER_VERSION = config("MCP_SERVER_VERSION", default="1.0.0")
   MCP_BASE_TEMPLATE = config("MCP_BASE_TEMPLATE", default="website/base.html")
   MCP_TOKEN_NAME_PREFIX = config("MCP_TOKEN_NAME_PREFIX", default="MCP")
   MCP_SUPPORTED_PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
   MCP_OAUTH_CODE_TTL_SECONDS = config("MCP_OAUTH_CODE_TTL_SECONDS", default=600, cast=int)
   MCP_ENABLE_OAUTH = config("MCP_ENABLE_OAUTH", default=True, cast=bool)
   MCP_VERBOSE_LOGGING = config("MCP_VERBOSE_LOGGING", default=False, cast=bool)
   MCP_TOOL_MODULES: list[str] = []
   ```

4. Register the `smallstack.mcp` logger in `config/settings/development.py` and `production.py`:

   ```python
   "smallstack.mcp": {
       "handlers": ["console"],
       "level": "INFO",
       "propagate": False,
   },
   ```

   Do **not** add a top-level `mcp` logger — it collides with the upstream `mcp` package's logger.

5. Wire URLs in `config/urls.py`:

   ```python
   from apps.mcp.urls import oauth_wellknown_urlpatterns

   urlpatterns = [
       # ...
       path("", include("apps.mcp.urls")),
       *oauth_wellknown_urlpatterns,
       # ...
   ]
   ```

6. Migrate:

   ```bash
   uv run python manage.py migrate mcp_server
   ```

7. Confirm:

   ```bash
   uv run python manage.py mcp_doctor
   ```

   All checks should be green. If APIToken admin shows WARN, add `explorer_enabled = True` to your `APITokenAdmin`.

## If your project uses a non-website base template

Override the consent page parent:

```python
MCP_BASE_TEMPLATE = "tabler/base.html"   # or your project's base
```

You can also override `apps/mcp/templates/mcp/authorize.html` locally — Django's template lookup picks the project-local copy first.

## Don't

- Don't try to import `apps.mcp` before migrating. The OAuthAuthorizationCode model needs to exist.
- Don't change `AppConfig.label` from `"mcp_server"`. That name avoids a collision with the `mcp` PyPI package.
