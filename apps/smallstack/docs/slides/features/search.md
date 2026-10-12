# Search

<div class="two-col" markdown="1">
<div class="col" markdown="1">

Real ranked search, one index, three access tiers.

- **FTS5 on SQLite, `tsvector` + GIN on Postgres** — BM25-style ranking, no external service
- **One flag per model** — `enable_search = True`, with `search_visibility` for tenancy
- **Ctrl-K omnibar + `/search/` page** — results respect each viewer's staff / signed-in / anonymous tier
- **`search_all` MCP tool** — the same index for AI agents and RAG over your help docs
- **SearchBuilder** — custom variants when the default ranking isn't the one you want

</div>
<div class="col" markdown="1">

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    search_fields = ["subject", "body"]
    enable_search = True
    search_access = SearchAccess.AUTHENTICATED

    @staticmethod
    def search_visibility(user, qs):
        return qs.filter(team__members=user)
```

</div>
</div>
