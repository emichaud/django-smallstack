# MCP architecture

Three layers, top-down. Each is a separate file under `apps/mcp/`.

```
HTTP / JSON-RPC     →  apps/mcp/views.py     +  apps/mcp/oauth_views.py
        ↓
Server registry     →  apps/mcp/server.py    (Server singleton, @tool, ToolContext)
        ↓
Tool implementations  apps/mcp/factory.py    (CRUDView introspection)
                    +  downstream apps/mcp_tools/*.py modules
```

## Request flow

```
POST /mcp
  ├─ McpHttpView.post()
  ├─ parse JSON body → method, id, params
  ├─ if method in {initialize, ping, notifications/*, resources/list, prompts/list}:
  │      handle locally without authenticating
  └─ else:
       ├─ authenticate(request)            → user, token (or 401 + WWW-Authenticate)
       ├─ set_context(ToolContext(user, token))
       ├─ dispatch on method:
       │     tools/list  → walk TOOL_REGISTRY
       │     tools/call  → check_tool_access, call handler (sync or async)
       │     other       → -32601
       └─ reset_context()
```

## File map

| File | Responsibility |
|---|---|
| `apps/mcp/apps.py` | `AppConfig(label="mcp_server")`. `ready()` imports `MCP_TOOL_MODULES` then runs the factory over `CRUDView._registry` |
| `apps/mcp/server.py` | Singleton `mcp.server.lowlevel.Server`, `TOOL_REGISTRY`, `@tool`, `ToolContext`, `current_context()` |
| `apps/mcp/auth.py` | `authenticate(request)` (bearer-only, wraps `_authenticate_api_request`), `check_tool_access(token, tool_def, mixins)` |
| `apps/mcp/oauth.py` | `verify_pkce`, `issuer_url` (X-Forwarded-Proto aware), `absolute_url` |
| `apps/mcp/oauth_views.py` | RFC 8414/9728 metadata, RFC 7591 DCR, AuthorizeView, token exchange, RFC 7009 revoke |
| `apps/mcp/views.py` | `McpHttpView` — GET banner + POST JSON-RPC dispatch |
| `apps/mcp/factory.py` | `register_mcp_tools_from_crudview(view_cls)` — emits list/get/create/update/delete tools using existing helpers |
| `apps/mcp/models.py` | `OAuthAuthorizationCode` (PKCE-bound, one-shot, 10-min TTL) |
| `apps/mcp/urls.py` | Routes; mounted at both `/mcp` and `/mcp/` |
| `apps/mcp/management/commands/mcp_doctor.py` | Diagnostics |
| `apps/mcp/templates/mcp/authorize.html` | Consent page (extends `MCP_BASE_TEMPLATE`, generic CSS) |

## Why CRUDView changes are tiny

The factory reads everything from existing CRUDView config: `model`, `fields`, `form_class`, `actions`, `mcp_actions`, `search_fields`, `filter_fields`, `get_list_queryset`, `can_update`, `can_delete`, `on_form_valid`. The three new attributes are pure metadata:

```python
enable_mcp = False                          # opt-in flag
mcp_description: str | None = None          # description for the LLM
mcp_actions: list | None = None             # restrict below `actions`
```

Plus `__init_subclass__` populates `CRUDView._registry` at class-definition time so the factory can run during `AppConfig.ready()` instead of waiting for URL config.

## Composable helpers — public API

`apps/smallstack/api.py` re-exports five internals as a stable surface for the factory + your own code:

| Public name | What it does | Implementation |
|---|---|---|
| `serialize(obj, fields, extra, expand)` | Object → dict, FK expansion, ISO dates | `_serialize` |
| `apply_search(qs, request, crud_config)` | `?q=` with date-smart matching | `_apply_list_search` |
| `apply_filters(qs, request, crud_config)` | Per-field filters | `_apply_list_filters` |
| `apply_ordering(qs, ordering, allowed)` | `?ordering=field1,-field2` | `_apply_ordering_fields` |
| `field_to_schema(name, form_field, model)` | Form field → JSON schema dict | `_field_to_schema` |

Use these in custom tools or your own views — don't reimplement.
