# Skill: Add a write-capable MCP tool

## When to use this skill
The user wants the LLM to create, modify, or delete records — not just read.

## Preferred path: use the factory

If the action is "create a record matching this form", the factory already emits `create_<singular>`:

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_mcp = True
```

That's it. The MCP `create_ticket` tool uses `view_cls.form_class` (or auto-generated ModelForm), calls `form.save()`, fires `on_form_valid(...)`. Validation is identical to the REST API.

## When you need a custom write tool

Two reasons to bypass the factory:

1. The write isn't a single ModelForm save (e.g., "create a ticket and assign it to least-busy rep").
2. You want different input fields than the form.

```python
from apps.mcp.server import tool, current_context
from apps.tickets.models import Ticket


@tool(
    "create_urgent_ticket",
    "Create an urgent ticket and auto-assign to the on-call rep.",
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body":  {"type": "string"},
        },
        "required": ["title", "body"],
        "additionalProperties": False,
    },
    write=True,
)
def create_urgent_ticket(args):
    ctx = current_context()
    rep = pick_on_call_rep()
    t = Ticket.objects.create(
        title=args["title"],
        body=args["body"],
        priority="urgent",
        owner=ctx.user,
        assignee=rep,
    )
    return {"id": t.pk, "assigned_to": rep.username}
```

## Tokens that can/can't write

| Token access_level | Read tools | Write tools |
|---|---|---|
| `readonly` | yes | **no** (RPC -32600 / HTTP 403) |
| `staff` | yes | yes |
| `auth` | yes | yes |

The OAuth consent page mints readonly tokens by default. Bumping a token to `staff` is a manual operation (admin or `manage.py shell`).

## Don't

- Don't call `model.objects.create(**args)` directly if a `form_class` exists. You'll skip validation that the REST + HTML paths enforce.
- Don't trust `args` without validating — JSON Schema validation isn't enforced by the dispatcher. Either run the form or validate manually.
- Don't forget `write=True`. Without it, readonly tokens can call your destructive tool.
