# Writing custom MCP tools

The factory covers CRUD. For aggregation, summary, or cross-cutting lookups, use the `@tool` decorator. These are exactly the "composability" wins for LLM chat — one tool call replaces N CRUD round-trips.

## Skeleton

```python
# apps/mcp_tools/summary.py
from apps.mcp.server import tool, current_context
from apps.tickets.models import Ticket


@tool(
    "ticket_summary",
    "Counts of tickets by status for the current user — use this instead of list_tickets when only counts matter.",
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

## Register the module

```python
# config/settings/smallstack.py
MCP_TOOL_MODULES = ["apps.mcp_tools.summary"]
```

`AppConfig.ready()` imports each entry at startup, the `@tool` decorator self-registers.

## Sync or async — either works

The dispatcher inspects the handler. Use plain `def` for ORM-heavy tools (sync ORM is fine). Use `async def` when calling external HTTP services with `httpx.AsyncClient`.

## Write tools

```python
@tool("send_invoice", "Email the invoice to the customer.", write=True)
def send_invoice(args):
    ...
```

`write=True` rejects readonly tokens. The reverse — gating a tool to `auth`-level only — uses `requires_access="auth"`.

## Reading the user

`current_context()` raises `LookupError` outside a dispatch, so tool callbacks can safely assume a `ToolContext` is set. Both `user` and `token` are attached.

## Naming

- snake_case
- verb-noun: `list_`, `get_`, `summary_`, `find_`, `recent_`, `count_`
- Prefer a stable name over a "smart" one — LLMs key off the exact string

## Return convention

Plain JSON-serializable Python (`dict`, `list`, `str`, `int`, `bool`, `None`). Datetimes are stringified by the dispatcher; QuerySets are not — call `list(qs)` and serialize per-item if you want one.
