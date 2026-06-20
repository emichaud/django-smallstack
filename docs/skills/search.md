# Search — adding it to a model + the MCP-RAG story

**Read this** before adding `enable_search = True` to a CRUDView or building any search-shaped feature. The patterns produce per-model search that works on the first try across SQLite/Postgres + lights up Claude's `search_X` MCP tool for RAG.

> **Prerequisites**: read [`modern-dark-theme.md`](modern-dark-theme.md) for UI patterns and [`cli-tools.md`](cli-tools.md) for the management commands.

## When to opt in

Add `enable_search = True` to a CRUDView when:

- Users will want to find records by typing words, not just by filtering structured fields
- The model has text fields with meaningful content (titles, descriptions, names, notes)
- You want Claude (or other MCP clients) to be able to answer "find tickets / users / docs about X" questions

**Don't** add it to:

- Pure relational/junction tables (UserGroup, etc) — nothing to search by text
- Models with only datetime or numeric fields — use `filter_fields` instead
- Models with millions of rows that will rebuild slowly — measure first, consider chunked rebuild

## The minimum opt-in

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_search = True
    search_fields = ["title", "description"]
```

That's enough. You get:

- An FTS5 virtual table (SQLite) or a search_vector column (Postgres — needs a migration)
- A `search_tickets(query, limit)` MCP tool registered with the MCP server
- Ticket results in the topbar omnibar (Ctrl+K) + `/smallstack/search/?q=` page

## The opinionated opt-in (recommended)

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_search = True
    search_fields = ["title", "description", "customer__name"]
    search_display = "title"           # what shows in the result row
    search_subtitle = "description"    # truncated to 160-200 chars in the UI
    search_weight = {                  # higher = more important for ranking
        "title": 3,
        "customer__name": 2,
        "description": 1,
    }
```

- **`search_fields`**: list of model field names. Can use `__` for related fields (`customer__name`). The first one is the default for snippet text.
- **`search_display`**: which field is the result-row title. Defaults to `str(obj)`. Strongly recommended to set explicitly so the row reads well.
- **`search_subtitle`**: which field provides the snippet text under the title. Truncated to ~200 chars.
- **`search_weight`**: per-field ranking weight (1-3). Affects BM25 (SQLite) and ts_rank (Postgres). Higher weights mean matches in that field rank higher.

## What gets generated per opt-in

When `apps.search` is in `INSTALLED_APPS` and a CRUDView has `enable_search = True`:

1. **SearchConfig.ready()** registers the view in `_search_registry`
2. **The active backend** creates the index structure (FTS5 table on SQLite, no-op on Postgres because the column comes from migration)
3. **post_save / post_delete signals** keep the index current
4. **MCP tool factory** registers `search_<plural>(query, limit)` in `TOOL_REGISTRY`
5. **Results appear** in the global search page, omnibar JSON, and Claude's tool list

## RAG with Claude Desktop

`enable_search = True` + `enable_mcp = True` on the same CRUDView turns Claude Desktop into a knowledge-aware assistant for that model. The user asks "what's the status of Acme's open tickets?" and:

1. Claude sees the MCP tools available: `list_tickets`, `get_ticket`, **`search_tickets`**, `update_ticket`, ...
2. Claude calls `search_tickets(query="acme", limit=10)` (it picked the right tool)
3. SmallStack runs the FTS5 query, returns ranked results with snippets
4. Claude reads the results, optionally calls `get_ticket(id=X)` for full detail on the most relevant
5. Claude answers the user with citations

No RAG pipeline code. No prompt templates. The LLM does the orchestration via MCP.

The help-docs are part of the same unified index — a separate `search_help(query, limit)` MCP tool lets Claude answer "how do I X in SmallStack?" questions about your bundled docs.

## Backend selection (you don't have to think about this)

| DB engine | Backend | Notes |
|---|---|---|
| `sqlite3` | `SQLiteFTSBackend` | FTS5 virtual table, BM25, porter stemming, prefix `term*` |
| `postgresql` | `PostgresFTSBackend` | Needs migration to add `search_vector` column + GIN index |
| anything else | `FallbackBackend` | `__icontains` OR — slow at scale, no ranking, no operators |

If a user runs your project on MySQL, search still works (fallback) but degrades past ~10k rows. The doctor's WARN row will say so.

## What to do after enabling

```bash
# SQLite: nothing required if you just added the model — but if rows
# existed before you opted in, populate the index:
uv run python manage.py rebuild_search_index <app_label>.<Model>

# Postgres: you need a migration first
uv run python manage.py makemigrations <app_label>
uv run python manage.py migrate
uv run python manage.py rebuild_search_index --all

# Verify
uv run python manage.py search_doctor
```

## Anti-patterns

**Don't** index huge text columns naively. Indexing a 50KB `body` field per row produces a slow index and a slow query. Use a `search_summary` column with the first 1-2 paragraphs, or filter the input via `search_fields` to short, targeted fields.

**Don't** index computed/property fields. `search_fields` must be real model fields the backend can read at index time. Computed properties don't update via signals.

**Don't** use `search_fields` for filtering — those are different concerns:
- `filter_fields`: structured equality / range filters in the list-page UI
- `search_fields`: free-text search

**Don't** add the omnibar's CSS classes to your own elements. `.omnibar-*` are reserved for the topbar overlay markup.

**Don't** override the MCP tool's description without thinking about the LLM. Claude reads the description to decide WHEN to call your tool. Write it for the LLM — be specific about what records exist and when retrieval helps.

## Verifying your work

After adding `enable_search = True`:

1. **CLI**: `uv run python manage.py search_doctor` — should show your model under "Search registry"
2. **CLI**: `uv run python manage.py search_doctor --explain` — confirms field list and MCP tool name
3. **Web**: `/smallstack/search/?q=<test term>` — should return results
4. **Web**: hit Ctrl+K on any page → omnibar opens → type term → see your model's results
5. **MCP**: `uv run python manage.py mcp_doctor --explain search_<plural>` — confirms tool is registered with the right input schema
6. **End-to-end**: connect Claude Desktop to your SmallStack instance, ask "find any \<model name\> mentioning \<term\>", verify Claude calls the tool

## Related

- [`apps/smallstack/docs/search.md`](../../apps/smallstack/docs/search.md) — user-facing reference
- [`mcp/build-mcp-solution.md`](mcp/build-mcp-solution.md) — how to design MCP features
- [`modern-dark-theme.md`](modern-dark-theme.md) — UI patterns the search page uses
