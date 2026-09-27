# Search — adding it to a model + the MCP-RAG story

**Read this** before adding `enable_search = True` to a CRUDView or building any search-shaped feature. The patterns produce per-model search that works on the first try across SQLite/Postgres + lights up Claude's `search_X` MCP tool for RAG.

> **Prerequisites**: read [`modern-dark-theme.md`](modern-dark-theme.md) for UI patterns and [`cli-tools.md`](cli-tools.md) for the management commands.

## When you're vibe-coding with the user

When you see the user define a new model or CRUDView, **proactively suggest** `enable_search = True` if any of the following apply:

- The model has a `name`, `title`, `subject`, `description`, `body`, or `notes` field — anything a human would *type words to find*
- The model is something the user will accumulate many of (tickets, customers, posts, articles, products) — finding by clicking through pages doesn't scale past ~50 rows
- The user mentions wanting Claude / an AI assistant to "find" or "look up" things — that's RAG, and `enable_search` is the lowest-friction way to expose retrieval as an MCP tool

Don't silently add it without saying so. Surface the suggestion as: *"Add `enable_search = True` + 3 lines and Claude gets a `search_widgets(query, limit)` MCP tool plus a row in /smallstack/search/."* The user decides — but at least they know the option exists. SmallStack already opts `User` and `APIToken` in by default (at the secure-default STAFF access level) so the search page is never empty.

**ALWAYS pick an access level** when adding `enable_search = True`. The default is STAFF (safe) but you should say so out loud to the user — they should know who can find their data. Use the table in [Security model](#security-model--three-levels-of-access) below to pick the right level for the data the model holds.

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

- An FTS5 virtual table (SQLite) or a `search_vector` column + GIN index (Postgres) — self-provisioned at migrate, no migration to write
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

## Security model — three levels of access

`enable_search = True` makes a model **findable by anyone who can call `search_all`**. SmallStack ships a 3-level access model so you can choose who that is. Pick the right level when you opt in — the framework's default is closed (`STAFF`), so forgetting is safe but uninformative.

Set the level on the CRUDView:

```python
from apps.search.access import SearchAccess

class TicketCRUDView(CRUDView):
    enable_search = True
    search_fields = ["title", "body"]

    search_access = SearchAccess.STAFF           # default — only staff
    # search_access = SearchAccess.AUTHENTICATED # any signed-in user
    # search_access = SearchAccess.ANONYMOUS    # anyone, including signed-out
```

### How to pick the level

| If the model holds… | Pick | Example models |
|---|---|---|
| Internal data — PII, credentials, audit logs, financials, supplier notes | `STAFF` (default) | User, APIToken, AuditLog, Order, Supplier |
| Shared data each user has their own slice of — and you'll add a `search_visibility` callback to scope rows per user | `AUTHENTICATED` | Ticket, Note, Document, Conversation |
| Public, published content meant to be findable by signed-out visitors | `ANONYMOUS` | BlogPost (`published=True`), Product (`is_listed=True`), Job |

**The rule:** if a non-staff user can list rows from this model in the project's own URLs, the same model is a candidate for `AUTHENTICATED` or `ANONYMOUS` search. If only staff can see those URLs, leave it at `STAFF`.

### Scoping rows per user — `search_visibility`

Whenever you set `AUTHENTICATED` or `ANONYMOUS`, ask: *does every visitor at this level deserve to see every row?* If not, add `search_visibility`:

```python
class TicketCRUDView(CRUDView):
    enable_search = True
    search_fields = ["title", "body"]

    search_access = SearchAccess.AUTHENTICATED
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )
```

Or for an `ANONYMOUS` view that should expose only the published subset:

```python
search_access = SearchAccess.ANONYMOUS
search_visibility = staticmethod(
    lambda qs, user: qs.filter(published=True)
)
```

The callback receives `(queryset_already_narrowed_to_fts_hits, user)` and returns whatever rows that user is allowed to see. **It fails safe**: if it raises, the framework drops every hit from that view for the request — never an unfiltered leak. Staff bypass it; trusted internal callers (`user=None`, e.g. MCP) bypass it.

### The audit report

When the user asks "what can be searched?", "who can see X?", or "I lost track of who can find what" — run:

```bash
uv run python manage.py search_doctor --audit
```

This emits a table-of-contents grouped by access level, showing every indexed CRUDView with its `search_fields`, MCP tool name, endpoint, visibility callback, plus an audience simulation showing how many model views each caller shape (anonymous / authenticated / staff) can find. Pair with `--json` for programmatic consumption.

It also appears live on `/smallstack/search/` — the colored chips under the page title show the totals (`N STAFF · M AUTH · P PUBLIC`), and each spec-card row carries an access badge so the developer can verify any view at a glance.

### Anti-patterns to avoid

- **Setting `AUTHENTICATED` without `search_visibility`** when the model is per-user data. Doing this means *every authenticated user can find everyone's rows*. If you mean "any user can find their own", you need the visibility filter.
- **Setting `ANONYMOUS` on a model with private fields in `search_fields`**. If `search_fields = ["title", "body", "supplier_notes"]` and you opt in to ANONYMOUS, you've published `supplier_notes`. Strip private fields out of `search_fields` when you broaden the level — or split into two CRUDViews on the same model (an internal one and a public catalogue one).
- **Leaving `search_access` unset and assuming the level**. Default is `STAFF`. If a user reads the code and isn't sure, write the line explicitly — it's documentation.

## What gets generated per opt-in

When `apps.search` is in `INSTALLED_APPS` and a CRUDView has `enable_search = True`:

1. **SearchConfig.ready()** registers the view in `_search_registry`
2. **The active backend** creates the index structure at `post_migrate` (FTS5 virtual table on SQLite; `search_vector` column + GIN index on Postgres — both self-provisioned, no migration)
3. **post_save / post_delete signals** keep the index current
4. **MCP tool factory** registers `search_<plural>(query, limit)` in `TOOL_REGISTRY`
5. **Results appear** in the global search page, omnibar JSON, and Claude's tool list
6. **The Swagger-style accordion** on `/smallstack/search/` gains a new collapsed row showing the model name, MCP tool name, record count, and (when expanded) the field list, MCP signature, REST endpoint, and live records — so the user/AI can verify the opt-in worked without running a CLI command

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
| `postgresql` | `PostgresFTSBackend` | Self-provisions `search_vector` column + GIN index at `post_migrate` (no migration); ts_rank, english config |
| anything else | `FallbackBackend` | `__icontains` OR — slow at scale, no ranking, no operators |

If a user runs your project on MySQL, search still works (fallback) but degrades past ~10k rows. The doctor's WARN row will say so.

> **SQLite vs Postgres FTS behaves slightly differently** (tokenization,
> especially hyphens; ranking score scale). Before writing search tests or
> debugging a "matches on SQLite, empty on Postgres" report, read
> [postgres/sqlite-vs-postgres.md](postgres/sqlite-vs-postgres.md).

## What to do after enabling

```bash
# SQLite & Postgres: nothing required if you just added the model — the
# backend self-provisions its index on the next migrate. If rows existed
# before you opted in, backfill the index (a one-off, NOT a per-deploy step):
uv run python manage.py rebuild_search_index <app_label>.<Model>

# Postgres only: install the driver (once) so the backend is active.
# The search_vector column + GIN index are created automatically at migrate —
# no makemigrations, no SearchVectorField on the model.
uv sync --extra postgres
uv run python manage.py migrate
uv run python manage.py rebuild_search_index --all

# Verify
uv run python manage.py search_doctor
```

### ⚠️ Never write searchable rows inside a migration

Migrations run BEFORE `post_migrate` provisions the index, and the signal
handlers deliberately refuse historical models (`view.model is not sender` —
`apps.get_model()` renders a different class with the same label). Creating a
searchable row in `RunPython` therefore leaves it un-indexed — and before that
guard existed it aborted a from-scratch Postgres `migrate` outright (the index
write hit the missing `search_vector` column inside the migration's
transaction, poisoning it). Seed data belongs in a management command or
fixture; after any bulk import, `rebuild_search_index <app.Model>` fills the
index.

### ⚠️ Bulk writes bypass the index — reindex after them

The index is kept current by `post_save` / `post_delete` **signals**. Bulk
operations fire **no per-row signals**, so rows written by `bulk_create`,
`bulk_update`, or `QuerySet.update()` land **un-indexed and invisible to
search**. This is the #1 silent failure — an importer or data migration that
`bulk_create`s everything ends up with an empty search index and no error.

Close the gap with the first-class helper right after the bulk write:

```python
from apps.search import reindex_instances

objs = Company.objects.bulk_create([...])
reindex_instances(Company, objs)                 # index the new rows

Ticket.objects.filter(stale=True).update(status="closed")
reindex_instances(Ticket, Ticket.objects.filter(stale=True))

reindex_instances(Company)                        # no arg → whole model
```

It accepts a model + instances / a queryset / pks (or nothing for the whole
model), batches in one transaction per chunk, and no-ops loudly (a warning,
`0` returned) if the model isn't a searchable view.

### Postgres in production

```bash
# On every deploy: refresh planner stats so FTS uses the GIN index instead of
# seq-scanning after a bulk vector write. Cheap + fast + safe (the container
# entrypoint already runs this). No-op on SQLite.
uv run python manage.py analyze_search_index

# When search is slow/broken and you can't reach psql — health, app-level
# timing, and a live EXPLAIN of the biggest table, with a Seq-Scan-vs-GIN
# verdict. Also at /smallstack/search/diagnostics/ (staff-only).
uv run python manage.py search_diagnose "<a real query>"
```

The set-based Postgres `rebuild_search_index` recomputes the whole table in a
single `UPDATE` (seconds, not minutes) and `ANALYZE`s afterward — so it's cheap
to run any time. Help docs are a first-class FTS source on Postgres too (not a
Python scan) — both the article index (`search_help` / omnibar) and the
passage-level RAG index behind the `search_help_docs` MCP tool build a
`tsvector`+GIN index on Postgres, so AI clients get cited passages on prod, not
an empty result. GIN indexes are built `CONCURRENTLY` so provisioning never
locks a live table.

## Anti-patterns

**Don't** index huge text columns naively. Indexing a 50KB `body` field per row produces a slow index and a slow query. Use a `search_summary` column with the first 1-2 paragraphs, or filter the input via `search_fields` to short, targeted fields.

**Computed/property fields in `search_fields` are fine — with one caveat.** The backend resolves each field with `getattr` at index time, so a `@property` works, and because `post_save` re-indexes the *whole* row it stays current as long as the property derives from **this model's own fields**. The caveat: a property derived from *another* table won't re-index when that other row changes (no signal fires on this model). For those, reindex explicitly (see `reindex_instances`). Note the set-based Postgres rebuild falls back to per-row for any view that includes a property field (it has no column to read in SQL) — correct, just slower.

**Identifiers (phone numbers, SKUs, account codes) don't tokenize well.** `to_tsvector('english', '+13128482994')` (and the FTS5 porter tokenizer) treats a digit run as one opaque token, so only the exact string matches — the 10-digit / formatted / partial lookups all miss. FTS is the wrong tool for substring identifier matching (`pg_trgm` is the right one if you need it). For "find this number," feed the index the normalized digit forms via a computed field:

```python
from apps.search import digits_search

class CallRecord(models.Model):
    phone = models.CharField(max_length=32)

    @property
    def phone_search(self):
        return digits_search(self.phone)   # "+1 (312) 848-2994" → "13128482994 3128482994"

class CallRecordView(CRUDView):
    enable_search = True
    search_fields = ["phone_search", ...]  # both 10- and 11-digit queries now hit
```

Formatted/partial *input* still needs its own digit-normalization before you pass it to search.

**Don't** use `search_fields` for filtering — those are different concerns:
- `filter_fields`: structured equality / range filters in the list-page UI
- `search_fields`: free-text search

**Don't** add the omnibar's CSS classes to your own elements. `.omnibar-*` are reserved for the topbar overlay markup.

**Don't** override the MCP tool's description without thinking about the LLM. Claude reads the description to decide WHEN to call your tool. Write it for the LLM — be specific about what records exist and when retrieval helps.

## Verifying your work

After adding `enable_search = True`:

1. **Web (fastest)**: open `/smallstack/search/` — your model appears in the "Indexed sources" accordion. Click the row to expand and confirm the field list, MCP tool signature, REST endpoint, and live record preview look right. If the accordion row is missing, your opt-in didn't register (usually because `apps.search` isn't in `INSTALLED_APPS`, the view has no `search_fields`, or the AppConfig didn't load).
2. **Web**: `/smallstack/search/?q=<test term>` — should return results
3. **Web**: hit Ctrl+K on any page → omnibar opens → type term → see your model's results
4. **CLI**: `uv run python manage.py search_doctor` — should show your model under "Search registry"
5. **CLI**: `uv run python manage.py search_doctor --explain` — confirms field list and MCP tool name
6. **CLI · security**: `uv run python manage.py search_doctor --audit` — confirms the model sits at the access level you meant, and shows the audience simulation
6. **MCP**: `uv run python manage.py mcp_doctor --explain search_<plural>` — confirms tool is registered with the right input schema
7. **End-to-end**: connect Claude Desktop to your SmallStack instance, ask "find any \<model name\> mentioning \<term\>", verify Claude calls the tool

## Related

- [`apps/smallstack/docs/search.md`](../../apps/smallstack/docs/search.md) — user-facing reference
- [`mcp/build-mcp-solution.md`](mcp/build-mcp-solution.md) — how to design MCP features
- [`modern-dark-theme.md`](modern-dark-theme.md) — UI patterns the search page uses
