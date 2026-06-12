# Skill: Enable MCP for a CRUDView

## When to use this skill
The user has an existing `CRUDView` and wants AI clients (Claude Desktop, Claude.ai Connectors) to be able to list, read, or modify its records.

## Steps

1. Open the `*_crud.py` (or wherever the CRUDView lives) for the target model.
2. Add three class attributes:

   ```python
   class WidgetCRUDView(CRUDView):
       model = Widget
       # ... existing config ...
       enable_mcp = True
       mcp_description = "One sentence telling the LLM what these records are and when to query them."
       # mcp_actions = [Action.LIST, Action.DETAIL]   # optional — narrow below `actions`
   ```

3. If the CRUDView lives in an app that isn't already in `INSTALLED_APPS`, add it. (Otherwise the class is never imported and `__init_subclass__` never registers it.)

4. Verify:

   ```bash
   uv run python manage.py mcp_doctor
   # → "Server registry  N tools registered" should include list_widgets, get_widget, ...
   ```

5. Test against a live token:

   ```bash
   TOKEN=$(uv run python manage.py create_api_token --user admin --name dev --access-level readonly)
   curl -s -X POST http://localhost:8005/mcp \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
   ```

## What gets generated

| Tool | When |
|---|---|
| `list_<base>` | always (if `Action.LIST` in `actions`) |
| `get_<singular>` | if `Action.DETAIL` in `actions` |
| `create_<singular>` | if `Action.CREATE` in `actions` |
| `update_<singular>` | if `Action.UPDATE` in `actions` |
| `delete_<singular>` | if `Action.DELETE` in `actions` |

`<base>` is `url_base` or the lowercase model name. `<singular>` is `model._meta.verbose_name`.

## Tenancy already works

The factory calls `view_cls.get_list_queryset(qs, request)` with `request.user` set to the token's user. If your CRUDView already scopes by `request.user`, MCP inherits it.

## Don't

- Don't add `mcp_*` attributes to a CRUDView that's never imported — verify the app is in `INSTALLED_APPS`.
- Don't try to override the generated tool names by hand; if you need a custom name, write a `@tool`-decorated function instead.
