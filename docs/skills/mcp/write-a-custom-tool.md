# Skill: Write a custom MCP tool

## When to use this skill
The user wants a tool that doesn't fit "list/get/create/update/delete one model" — usually an aggregate (`summary_`, `count_`), a cross-model lookup (`find_anything`), or a side-effect (`send_invoice`).

## Steps

1. Create `apps/mcp_tools/<topic>.py` (create the package if it doesn't exist — `apps/mcp_tools/__init__.py` empty).

2. Define the tool:

   ```python
   from apps.mcp.server import tool, current_context
   from apps.tickets.models import Ticket


   @tool(
       "ticket_summary",
       "Counts of tickets by status for the current user. Use this instead of list_tickets when only counts matter.",
       input_schema={"type": "object", "properties": {}, "additionalProperties": False},
   )
   def ticket_summary(args):
       user = current_context().user
       qs = Ticket.objects.filter(owner=user)
       return {
           "open":     qs.filter(status="open").count(),
           "pending":  qs.filter(status="pending").count(),
           "closed":   qs.filter(status="closed").count(),
       }
   ```

3. Register the module in settings:

   ```python
   # config/settings/smallstack.py
   MCP_TOOL_MODULES = ["apps.mcp_tools.ticket_summary"]
   ```

4. Restart the dev server, verify with `mcp_doctor`.

## Conventions

- `name`: snake_case, verb-noun (`list_`, `summary_`, `find_`, `recent_`, `count_`, `send_`).
- `description`: one sentence, written for the LLM. Tell it *when* to call this tool over alternatives.
- `input_schema`: JSON Schema object. Always set `additionalProperties: False` so the LLM doesn't make up params.
- Return JSON-serializable Python (dict, list, str, int, bool, None, datetime — the dispatcher stringifies datetime via `json.dumps(default=str)`).

## Write tools

```python
@tool("send_invoice", "Email the invoice to the customer for the given pk.", write=True)
def send_invoice(args):
    ...
```

`write=True` ⇒ readonly tokens rejected.

## Access gating beyond write/read

```python
@tool("manage_users", "Suspend a user.", requires_access="auth")
def manage_users(args):
    ...
```

Order: `readonly` < `staff` < `auth`. A token below the required level gets 403.

## Sync or async — pick whichever fits

Sync `def` is fine for ORM-heavy work (the dispatcher detects and runs sync handlers directly). Use `async def` only when calling external HTTP / IO.

## Don't

- Don't return querysets — `json.dumps` can't serialize them. Use `list(qs)` + serialize per-item.
- Don't read `request` — use `current_context().user` / `current_context().token`.
- Don't bypass `get_list_queryset` if you can call it. Tenancy is one of the things that makes MCP safe.
