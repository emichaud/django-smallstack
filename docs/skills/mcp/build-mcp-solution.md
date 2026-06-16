# Skill: Build an MCP solution

## When to use this skill
The user says something like:
- "I want Claude to be able to look up customers"
- "Let Claude file support tickets for me"
- "Can Claude summarize what's open this week?"
- "Make my Foo model usable by Claude"

You need to translate that into the right MCP surface — without overbuilding.

## The decision tree

Start here, top to bottom. Pick the first option that fits; don't skip.

```
1. Does the user want Claude to read/write existing records
   in a model that already has a CRUDView?
   └─ YES → Add `enable_mcp = True` to that CRUDView. Done.
            (3 lines. Skill: enable-mcp-for-a-model.md)
   └─ NO  → continue

2. Does the model exist but no CRUDView yet?
   └─ YES → Build the CRUDView with the normal admin surface first
            (per the CRUDView docs), THEN add `enable_mcp = True`.
            Cost: ~30 min. The CRUDView is reusable for HTML + REST + MCP.
   └─ NO  → continue

3. Does the user want a computed/aggregate answer
   ("how many open tickets", "total revenue this month")?
   └─ YES → Write a custom @tool function. Don't try to model it.
            (Skill: write-a-custom-tool.md)
   └─ NO  → continue

4. Does the user want a cross-model lookup
   ("find any object matching X across customers, tickets, invoices")?
   └─ YES → @tool function that queries multiple models and merges
            results. Returns a list of `{type, id, snippet}` dicts.
   └─ NO  → continue

5. Does the user want Claude to trigger an external side effect
   (send email, kick off background job, call an API)?
   └─ YES → @tool with `write=True`. Return a status dict.
            (Skill: add-a-write-tool.md)
   └─ NO  → re-read the user's request — you may have misunderstood.
```

## What the resulting code looks like

### Case 1 — CRUDView opt-in (most common)

User: *"Let Claude read my Customer records and create new tickets."*

```python
# apps/support/views.py — already has these CRUDViews from existing work
class CustomerCRUDView(CRUDView):
    model = Customer
    # ... existing config (actions, filter_fields, etc.) ...
    enable_mcp = True
    mcp_description = "Customers who can submit support tickets."

class TicketCRUDView(CRUDView):
    model = Ticket
    enable_mcp = True
    mcp_description = "Support tickets. Filter by status='open' for unresolved work."
    mcp_actions = [Action.LIST, Action.DETAIL, Action.CREATE]  # read+create, no destructive ops
    api_expand_fields = ["customer", "assignee"]  # nest FKs in responses
```

Result: 8 MCP tools (`list_customers`, `get_customer`, `list_tickets`, `get_ticket`, `create_ticket`, plus the inline `customer`/`assignee` nesting), all wired through the same `get_list_queryset` tenancy hook the REST API uses.

### Case 2 — Aggregate / computed

User: *"Show Claude how many open tickets there are."*

```python
# apps/support/mcp_tools.py — autodiscover picks this up
from apps.mcp.server import tool, current_context
from apps.support.models import Ticket


@tool(
    "ticket_summary",
    "Counts of tickets by status for the current user. Use this instead of "
    "list_tickets when only counts matter — it's one call vs many.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
def ticket_summary(args):
    user = current_context().user
    qs = Ticket.objects.filter(owner=user)
    return {
        "open":   qs.filter(status="open").count(),
        "pending": qs.filter(status="pending").count(),
        "closed":  qs.filter(status="closed").count(),
    }
```

Why a custom tool not a CRUDView aggregation: the LLM gets the answer in 1 call. CRUDView's aggregate query params work but the LLM has to know to use them; an explicit `summary_*` tool makes its job easier.

### Case 3 — Cross-model search

User: *"When Claude asks about 'Acme', it should find Acme the customer, any ticket referencing Acme, and any invoice."*

```python
# apps/support/mcp_tools.py
from apps.mcp.server import tool, current_context


@tool(
    "find_anything",
    "Cross-model search. Returns matching customers, tickets, and invoices "
    "for a query string. Use when the user's request is vague about which "
    "model to search.",
    input_schema={
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Search term"},
            "limit": {"type": "integer", "default": 10, "maximum": 50},
        },
        "required": ["q"],
        "additionalProperties": False,
    },
)
def find_anything(args):
    from apps.support.models import Customer, Ticket, Invoice

    user = current_context().user
    q = args["q"]
    limit = args.get("limit", 10)

    hits = []
    for c in Customer.objects.filter(owner=user, name__icontains=q)[:limit]:
        hits.append({"type": "customer", "id": c.pk, "snippet": str(c)})
    for t in Ticket.objects.filter(owner=user, title__icontains=q)[:limit]:
        hits.append({"type": "ticket", "id": t.pk, "snippet": str(t)})
    for i in Invoice.objects.filter(owner=user, ref__icontains=q)[:limit]:
        hits.append({"type": "invoice", "id": i.pk, "snippet": str(i)})
    return {"query": q, "hits": hits[:limit]}
```

### Case 4 — Side effect (write tool)

User: *"When Claude resolves a ticket, send the customer a thank-you email."*

```python
@tool(
    "send_resolution_email",
    "Email the customer to confirm resolution. Use after closing a ticket.",
    input_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "integer"},
            "note": {"type": "string", "description": "Optional addition to the boilerplate."},
        },
        "required": ["ticket_id"],
        "additionalProperties": False,
    },
    write=True,  # readonly tokens get 403
)
def send_resolution_email(args):
    from apps.support.models import Ticket
    from apps.support.tasks import send_ticket_resolution_email

    user = current_context().user
    try:
        t = Ticket.objects.filter(owner=user).get(pk=args["ticket_id"])
    except Ticket.DoesNotExist:
        return {"error": f"Ticket {args['ticket_id']} not found"}

    send_ticket_resolution_email(t.pk, args.get("note", ""))
    return {"sent": True, "ticket_id": t.pk, "to": t.customer.email}
```

## Naming conventions (so Claude calls the right thing)

| Prefix | Meaning |
|---|---|
| `list_<plural>` | Returns multiple records with filters |
| `get_<singular>` | Returns one record by PK |
| `create_<singular>` | Makes a new record (write) |
| `update_<singular>` | Modifies one record (write) |
| `delete_<singular>` | Removes one (write) |
| `summary_<plural>` | Returns counts/stats |
| `find_<noun>` | Search across one or more types |
| `recent_<plural>` | Most recently changed records |
| `count_<plural>` | Single integer count |
| `send_<noun>` | Side-effect "send X" (write) |

`list_/get_/create_/update_/delete_` are reserved for the factory. If you want a custom variant, use a different verb (e.g. `search_tickets` not `list_tickets`).

## Gotchas (in order of how often they bite)

1. **Tenant scoping**: factory tools call `view_cls.get_list_queryset(qs, request)` automatically. Custom `@tool` functions must do their own `.filter(owner=user)` — `current_context().user` is the entry point.

2. **FK fields come back as bare PKs**: factory tools default to integer PKs in JSON. Add `api_expand_fields = ["customer", "assignee"]` on the CRUDView for `{"id": 6, "name": "Acme"}` nesting. Custom tools should nest manually (or serialize like the factory does).

3. **`mcp_description` is for the LLM, not the dev**: write what context the LLM needs to decide *when* to use the tool. "Tickets" is bad. "Support tickets. Filter by status='open' to find work" is good.

4. **`mcp_descriptions={Action.X: "..."}`** is the escape hatch for per-action overrides. By default each action gets a grammar-correct prefix (`"List ..."`, `"Get a single ..."`) — see `mcp-enable-models.md`.

5. **Don't write a tool when a filter would do**: if the user wants `list_tickets` to support `?status=open&priority=urgent`, that's `filter_fields = ["status", "priority"]` on the CRUDView, not a custom `urgent_tickets` tool.

## How to validate the design

After wiring (whether CRUDView attr or `@tool`):

1. **Static check** — `mcp_doctor --explain TOOL_NAME` shows what Claude will see. If the description is generic or the schema is missing fields, fix at the source (not at the tool).

2. **Live check** — `make mcp-test` to confirm the HTTP path works.

3. **LLM check** — connect Claude Desktop and ask the question in plain English: *"How many open tickets do I have?"* If Claude picks the wrong tool, the descriptions are wrong.

See [`verify-mcp.md`](verify-mcp.md) for the full verify checklist.

## Don't

- Don't try to build an "AI agent" inside MCP tools. Tools are simple verbs Claude calls; Claude is the agent.
- Don't make tools that take callback URLs, webhooks, or async results. MCP is request/response.
- Don't make `tools/list` return 50+ tools just because you have 10 CRUDViews × 5 actions each. The LLM gets confused. Use `mcp_actions = [Action.LIST, Action.DETAIL]` to narrow read-only views, or expose only the top 2–3 CRUDViews and add `@tool` aggregates for the rest.
- Don't put `@tool`s in random modules. Use `mcp_tools.py` per app (autodiscovered) or list explicitly in `MCP_TOOL_MODULES`.

## Related

- [`enable-mcp-for-a-model.md`](enable-mcp-for-a-model.md) — CRUDView opt-in details
- [`write-a-custom-tool.md`](write-a-custom-tool.md) — `@tool` decorator details
- [`add-a-write-tool.md`](add-a-write-tool.md) — write-tool patterns + access control
- [`verify-mcp.md`](verify-mcp.md) — how to confirm what you built works
- [`configure-mcp.md`](configure-mcp.md) — settings recipes
- [`debug-mcp-failure.md`](debug-mcp-failure.md) — when something breaks
