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

## Sync by default

Write a plain `def` and call the ORM directly. Every bundled tool does. `/mcp` is served by a WSGI thread that waits for your handler to finish, so `async def` buys no concurrency: the request costs the same thread either way.

`async def` is still accepted, for a tool that genuinely awaits external I/O. The dispatcher runs it through `async_to_sync`, so wrap any ORM call in `sync_to_async` (keep the default `thread_sensitive=True`) and it lands on the request's own thread and connection. Never drive a handler with `asyncio.run` — in a test or anywhere else — because that sends the ORM work to a shared background thread outside the request's transaction. `test_async_dispatch_thread.py` pins this.

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
