---
title: Search
description: FTS5 + Postgres FTS keyword search with per-CRUDView opt-in, MCP tool, omnibar
---

# Search

SmallStack ships a unified keyword search across your models — opt-in per CRUDView, with results visible in the topbar omnibar (Ctrl+K), a dedicated `/smallstack/search/` page, a REST endpoint, and an MCP tool Claude can call directly.

> **For AI agents adding search to a model**, the prescriptive skill is [`docs/skills/search.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/search.md).

## One flag, four surfaces

```python
from apps.smallstack.crud import CRUDView, Action

class TicketCRUDView(CRUDView):
    model = Ticket
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    enable_search = True
    search_fields = ["title", "description", "customer__name"]
    search_display = "title"          # row title in results
    search_subtitle = "description"   # secondary line
    search_weight = {                 # per-field weight (optional)
        "title": 3,
        "customer__name": 2,
        "description": 1,
    }
```

That single declaration produces:

| Surface | URL / API |
|---|---|
| Dedicated search page | `/smallstack/search/?q=acme` |
| Topbar omnibar (Ctrl+K from any page) | overlay on every page |
| REST endpoint | `GET /smallstack/search/omnibar/?q=acme` |
| MCP tool for Claude | `search_tickets(query, limit)` |
| Cross-model MCP tool | `search_all(query, limit_per_model)` |

## Backend selection

The right backend wires up automatically based on `DATABASES['default']['ENGINE']`:

| Database | Backend | Features |
|---|---|---|
| SQLite | `SQLiteFTSBackend` (FTS5) | BM25 ranking, porter stemming, phrase queries, prefix `term*` |
| PostgreSQL | `PostgresFTSBackend` | `SearchVector` + GIN index + `SearchRank`, english config |
| MySQL / other | `FallbackBackend` | `__icontains` OR (graceful, but slow at scale — recommended: switch to SQLite or Postgres) |

You write the same code regardless of backend. The user-facing query syntax is the same too.

## Query syntax

| User types | Means |
|---|---|
| `acme` | Single word match |
| `acme support` | Both words (implicit AND) |
| `"customer support"` | Exact phrase |
| `refund*` | Prefix match — also `refunding`, `refunded` |
| `acme OR beta` | Either word |
| `api -slow` | API but not `slow` |

The fallback backend treats operators as literal text (no FTS engine), so quoted phrases and `-` exclusion only work on SQLite + Postgres. Documented in the doctor's WARN output.

## Stemming

SQLite FTS5 uses the porter tokenizer — typing `complain` matches "complains", "complained", "complaining". PostgreSQL uses the `english` config (also porter-based). The fallback backend does substring matching, so `complain` only matches the literal substring.

## Setup steps after enabling search

### SQLite

Nothing to do. The FTS5 virtual table is created at startup the first time `SearchConfig.ready()` registers the view. To index existing rows that were saved before you enabled search:

```bash
uv run python manage.py rebuild_search_index support.Ticket
# or rebuild every indexed model
uv run python manage.py rebuild_search_index --all
```

### PostgreSQL

You need a migration that adds the `search_vector` column + GIN index to the model:

```python
# Inside your support/migrations/0007_ticket_search_vector.py
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("support", "0006_previous_migration")]
    operations = [
        migrations.AddField(
            model_name="ticket",
            name="search_vector",
            field=SearchVectorField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=GinIndex(fields=["search_vector"], name="ticket_search_vector_idx"),
        ),
    ]
```

Then `make migrate && uv run python manage.py rebuild_search_index --all`.

## Verifying

```bash
uv run python manage.py search_doctor          # health checks
uv run python manage.py search_doctor --explain  # dump every indexed model + MCP tool name
```

Open `/smallstack/search/?q=test` and hit Ctrl+K on any page for the omnibar.

## RAG via Claude Desktop / Connectors UI

This is the killer feature. With `enable_search = True` and `enable_mcp = True` on the same CRUDView, Claude Desktop gets a `search_tickets(query, limit)` MCP tool out of the box. The user asks Claude "what tickets do we have about acme?" and Claude calls the tool, reads the ranked results, and answers — no RAG pipeline code required.

Combined with the help-docs integration, the same Claude conversation can ask "how do I add a custom palette in SmallStack?" and get an answer from the bundled docs via `search_help`.

## Help docs

The help/docs system feeds the same index. Search results group by source (your models + a "Help & Docs" group). The `search_help(query, limit)` MCP tool gives Claude direct access to the bundled SmallStack documentation.

## What this doesn't do (yet)

- **Vector / semantic search**: keyword only in v0.11.0. Vector embeddings (sqlite-vec / pgvector) for hybrid keyword+vector RAG ship in v0.12.0 with the same `enable_search = True` opt-in pattern plus a new `enable_vector = True` flag.
- **Faceted search in the omnibar**: filter combinators are separate from `?q=` for now. The CRUDView list pages still have their own `filter_fields` for that.
- **Synonyms / custom stopwords / custom tokenizers**: defaults to `english`. Both FTS5 and Postgres FTS support customization; override per-view in a future release.
- **External engines** (Meilisearch / Typesense / Algolia): documented as future SearchBackend implementations. Implement the protocol in `apps/search/backends/base.py:SearchBackend` and register.

## Related

- [`docs/skills/search.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/search.md) — AI skill for adding search to a model
- [`mcp.md`](mcp.md) — the MCP server that exposes `search_X` tools
- [`api-doctor.md`](api-doctor.md) — sibling diagnostic for the REST surface
- [`cli-reference.md`](cli-reference.md) — `search_doctor` and `rebuild_search_index` commands
