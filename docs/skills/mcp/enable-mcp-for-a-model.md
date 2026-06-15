# Skill: Enable MCP for a CRUDView

## When to use this skill
The user has an existing `CRUDView` and wants AI clients (Claude Desktop, Claude.ai Connectors) to be able to list, read, or modify its records.

## Minimum

```python
class WidgetCRUDView(CRUDView):
    model = Widget
    # ... existing config ...
    enable_mcp = True
    mcp_description = "One sentence telling the LLM what these records are and when to query them."
    # mcp_actions = [Action.LIST, Action.DETAIL]   # optional — narrow below `actions`
```

That's the whole opt-in. The factory does the rest at app startup.

## Required: make sure the CRUDView gets imported

`CRUDView._registry` populates via `__init_subclass__`, which only fires when Python actually executes the `class WidgetCRUDView(CRUDView):` line. Two ways to guarantee that:

1. **Default: let `MCP_AUTODISCOVER` handle it.** At startup the MCP app walks every installed app and tries to import `<app>.views` and `<app>.mcp_tools`. If your CRUDView lives in one of those modules, you're done — no further action.

2. **Custom location: import explicitly from `AppConfig.ready()`.** If your CRUDView lives in something other than `views.py` / `mcp_tools.py` (e.g. `apps/your_app/crud.py`), add the import yourself:

   ```python
   # apps/your_app/apps.py
   class YourAppConfig(AppConfig):
       name = "apps.your_app"

       def ready(self):
           from . import crud   # any module that defines the CRUDView
   ```

Either way, **the app must precede `apps.mcp` in `INSTALLED_APPS`** so its `ready()` runs first.

If you set `enable_mcp = True` and `mcp_doctor` shows the registry empty, it now WARNs with the orphan file and a one-line fix — but the autodiscover step makes this rare in practice.

## Filtering

`filter_fields` is the killer feature for LLM usability. Each field listed becomes a typed input on the `list_*` tool, so the LLM can compose targeted queries in one call:

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_mcp = True
    mcp_description = "Support tickets."
    filter_fields = ["status", "priority", "customer"]
    search_fields = ["title", "body"]
```

The MCP `list_tickets` tool then accepts `{"status": "open", "priority": "urgent", "q": "printer"}` natively — no extra code.

## FK serialization

By default FKs come back as bare PKs:

```json
{"id": 22, "customer": 6, "technician": 4}
```

That's useless to the LLM without a follow-up call. Two workarounds:

**(a) Expand inline** via the existing `api_expand_fields` (the factory passes it through):

```python
api_expand_fields = ["customer", "technician"]
```

Now you get:

```json
{"id": 22, "customer": {"id": 6, "name": "Acme Corp"}, "technician": {"id": 4, "name": "alice"}}
```

**(b) Expose the related model as its own MCP CRUDView** (LIST + DETAIL only is usually enough so the LLM can resolve names on demand):

```python
class TechnicianCRUDView(CRUDView):
    model = User
    enable_mcp = True
    mcp_actions = [Action.LIST, Action.DETAIL]
    mcp_description = "Use to resolve technician FKs from tickets to names."
```

## Tool naming

| Tool | When | Default name |
|---|---|---|
| `list_<plural>` | `Action.LIST` in `actions` | `url_base` or `verbose_name_plural` |
| `get_<singular>` | `Action.DETAIL` | `verbose_name` |
| `create_<singular>` | `Action.CREATE` | `verbose_name` |
| `update_<singular>` | `Action.UPDATE` | `verbose_name` |
| `delete_<singular>` | `Action.DELETE` | `verbose_name` |

For a symmetric, custom name pair, set both:

```python
url_base = "tickets"      # web URL stays whatever it is
mcp_singular = "ticket"   # → list_tickets, get_ticket, create_ticket, ...
mcp_plural   = "tickets"
```

Without overrides, existing CRUDViews keep their pre-P23 names — the change is purely opt-in.

## Tenancy

The factory calls `view_cls.get_list_queryset(qs, request)` with `request.user` set to the token's user. If your CRUDView already scopes by `request.user`, MCP inherits it. The same applies to `can_update(obj, request)` and `can_delete(obj, request)` for row-level perms.

## Verify

```bash
uv run python manage.py mcp_doctor       # should show list_<x>, get_<x>, ...

TOKEN=$(uv run python manage.py create_api_token admin --name dev --access-level readonly)
curl -s -X POST http://localhost:8005/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
```

If the registry is empty, mcp_doctor now WARNs and tells you exactly which file holds the orphan `enable_mcp = True`.

## Don't

- Don't add `mcp_*` attributes to a CRUDView that lives in an uncommon module without either (a) trusting autodiscover or (b) importing it from your `AppConfig.ready()`.
- Don't try to override the generated tool names piecemeal — use `mcp_singular`/`mcp_plural`. For tools that aren't list/get/create/update/delete, use `@tool` instead.
