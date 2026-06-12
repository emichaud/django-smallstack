# Enable MCP for a CRUDView

One line opts in. The factory in `apps/mcp/factory.py` walks `CRUDView._registry` at app-ready time, finds anything with `enable_mcp = True`, and emits MCP tools.

## Minimum

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    fields = ["title", "status", "owner"]
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_mcp = True
```

Generates:

| Tool | Description | Write? |
|---|---|---|
| `list_tickets` | Search + filter + paginate | no |
| `get_ticket` | Fetch one by pk | no |
| `create_ticket` | ModelForm save | yes |
| `update_ticket` | PATCH-style merge | yes |
| `delete_ticket` | Honors `can_delete` | yes |

`list_*` accepts `q` (when `search_fields` is set), each field in `filter_fields`, `ordering`, and `limit` (default 50, max 200).

## Tell the LLM what the tool is for

```python
mcp_description = "Customer support tickets. Filter by status='open' to find unresolved work; use search to match by title."
```

This goes into the tool's `description` field. AI clients read it to decide *when* to call the tool. Write for the LLM, not the dev.

## Narrow which actions become MCP tools

Keep web writes, expose MCP as read-only:

```python
actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]  # web
mcp_actions = [Action.LIST, Action.DETAIL]                                            # MCP
```

`None` (the default) means "follow `actions`".

## Tenancy

MCP tools call `view_cls.get_list_queryset(qs, request)` exactly like the REST API does. If your CRUDView already scopes the queryset to `request.user`, MCP inherits that automatically.

## Staff-only

If `StaffRequiredMixin` is in `mixins`, all auto-derived tools require a staff-level token. The dispatcher returns RPC -32600 / HTTP 403 otherwise.

## Verify

```bash
uv run python manage.py mcp_doctor       # registry should list your new tools
```
