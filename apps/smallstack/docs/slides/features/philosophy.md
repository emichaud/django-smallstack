# Philosophy

<div class="two-col" markdown="1">
<div class="col" markdown="1">

A platform to build apps on, not a starter to grow out of.

- **Use what Django gives you** — before adding a package, check if Django already has it
- **One declaration, every surface** — a model + CRUDView becomes HTML, REST, MCP, search, webhooks and CLI
- **The built-in apps use public seams** — your app registers through the same hooks they do
- **Production-ready defaults** — secure settings, typed code, SQLite or Postgres, Docker + Kamal

</div>
<div class="col" markdown="1">

```python
# apps/tickets/views.py
class TicketCRUDView(CRUDView):
    model = Ticket
    list_columns = ["id", "title", "status"]

    enable_api      = True  # REST + OpenAPI
    enable_mcp      = True  # Claude tools
    enable_search   = True  # full-text search
    enable_webhooks = True  # signed events
```

</div>
</div>
