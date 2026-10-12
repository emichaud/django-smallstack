# One model, every surface

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Declare a `CRUDView` once and flip the flags. The same form, queryset and permission logic is emitted on every surface.

- **HTML** — themed list / detail / create / update / delete pages
- **REST** — Bearer auth, OpenAPI 3.0, Swagger UI, ReDoc, typed clients
- **MCP** — `list_tickets`, `get_ticket`, `create_ticket`… under OAuth + PKCE
- **Search** — ranked full-text with a Ctrl-K omnibar and an MCP retrieval tool
- **Webhooks & feeds** — signed events on change, RSS/Atom for any model
- **CLI** — `sc ls / get / new / set / rm`, same validation and audit as REST

</div>
<div class="col" markdown="1">

```
$ sc ls tickets.Ticket --json
$ curl -H "Authorization: Bearer $TOKEN" \
    /api/tickets/?status=open
$ # Claude Desktop → tools/list
list_tickets  get_ticket  create_ticket
update_ticket delete_ticket search_tickets
```

</div>
</div>
