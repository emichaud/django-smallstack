---
title: Search
description: FTS5 + Postgres FTS keyword search with per-CRUDView opt-in, MCP tool, omnibar
---

# Search

SmallStack ships a unified keyword search across your models — opt-in per CRUDView, with results visible in the topbar omnibar (Ctrl+K), a dedicated `/smallstack/search/` page, a REST endpoint, and an MCP tool Claude can call directly.

`User` and `APIToken` are opted in by default, so a fresh SmallStack clone has a working search experience without any code changes — open `/smallstack/search/` to see the indexed-sources accordion populated from day one.

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

The fastest check is to open `/smallstack/search/` itself. The page has an **Indexed sources** accordion — one collapsed row per opted-in source. Each row shows the kind (MODEL / DOC), the MCP tool name, the human label, and the record count. Click a row to expand a Swagger-style detail panel:

- **Indexed fields** — every field in `search_fields`, with the display field highlighted in the accent color and the subtitle field in a lighter tint (so it's obvious what shows up in result rows)
- **MCP tool** — the full signature Claude sees: `search_widgets(query: str, limit: int = 10)`
- **Web endpoint** — the GET URL that returns the same data as HTML
- **Browse latest** — the most recent records, clickable
- **Try a query** — pill links to one-click example searches

The accordion is the canonical answer to "did my opt-in work?" — if your model isn't there, the registration failed. CLI commands give the same information:

```bash
uv run python manage.py search_doctor          # health checks
uv run python manage.py search_doctor --explain  # dump every indexed model + MCP tool name
```

Hit Ctrl+K on any other page for the omnibar.

## RAG via Claude Desktop / Connectors UI

This is the killer feature. With `enable_search = True` and `enable_mcp = True` on the same CRUDView, Claude Desktop gets a `search_tickets(query, limit)` MCP tool out of the box. The user asks Claude "what tickets do we have about acme?" and Claude calls the tool, reads the ranked results, and answers — no RAG pipeline code required.

Combined with the help-docs integration, the same Claude conversation can ask "how do I add a custom palette in SmallStack?" and get an answer from the bundled docs via `search_help`.

## Help docs

The help/docs system feeds the same index. Search results group by source (your models + a "Help & Docs" group). The `search_help(query, limit)` MCP tool gives Claude direct access to the bundled SmallStack documentation.

## Security model — secure by default, opt-in to broaden

Search exposes data across every registered model. The same row that lives behind a staff-gated list page would, without protection, leak via cross-model search to whoever can hit `/search/`. Two per-view knobs control this. Both default to the safe end.

| Attribute on a `CRUDView` | Type | Default | Meaning |
|---|---|---|---|
| `search_access` | one of `SearchAccess.STAFF` / `AUTHENTICATED` / `ANONYMOUS` | `STAFF` | The level a caller must reach to see hits from this view. Strict supersets: any level grants the level above. |
| `search_visibility` | `(queryset, user) -> queryset` or `None` | `None` | Optional per-user row filter. Runs *after* the FTS query returns candidate ids and *only* for non-staff callers. Receives `AnonymousUser` when the view is `ANONYMOUS` and the visitor is signed-out. |

The gates live in `apps.search.registry.search_all(query, user=...)` and `apps.search.registry.get_indexed_sources(user=...)`. The HTTP views (admin search, omnibar, public website search) plumb `request.user` through. MCP tools call with `user=None` (trusted internal — they have their own access-level gate via the API token).

### The three access levels

| Level | Constant | Who can find rows |
|---|---|---|
| Staff | `SearchAccess.STAFF` (default) | `is_staff` users + trusted internal callers (`user=None`) |
| Authenticated | `SearchAccess.AUTHENTICATED` | Any signed-in user |
| Anonymous | `SearchAccess.ANONYMOUS` | Anyone, including signed-out visitors |

Resolution order per registered view:

```
caller            → result for a view declared at level X
─────────────────────────────────────────────────────────
user is None      → visible (trusted internal — bypass)
user.is_staff     → visible (bypass)
view.access == STAFF                  → hidden for everyone else
view.access == AUTHENTICATED          → visible only if signed in
view.access == ANONYMOUS              → always visible
```

### The starter pattern (what the default `make setup` ships)

SmallStack opts the bundled `User` and `APIToken` CRUDViews into search at the default `STAFF` level. The `/search/` page itself is *open to anonymous visitors* — they can search the help docs (broadly readable by design) but see zero hits from any user/token data. This demonstrates the full surface without leaking anything sensitive:

```
URL                          who can hit it         what they can find
────────────────────────────────────────────────────────────────────────
/search/   (public)          everyone               help docs +
                                                    anonymous-opted-in models
/smallstack/search/  (admin) staff only             everything indexed
```

That gives downstream projects a concrete, demonstrable security pattern out of the box — and the recipes below let you broaden access per CRUDView without rewriting any plumbing.

### Recipe 1 — keep it staff-only (default)

Do nothing. Any CRUDView with `enable_search = True` is staff-only. This is the right answer for User, APIToken, AuditLog, internal stock counts, anything else where a leak across rows would be a problem.

```python
class UserCRUDView(CRUDView):
    model = User
    enable_search = True
    search_fields = ["username", "email", "first_name", "last_name"]
    # search_access defaults to SearchAccess.STAFF — non-staff see zero hits.
```

### Recipe 2 — readable by any authenticated user

When the data is meant to be findable by everyone signed in but not by anonymous visitors (a shared internal knowledge base, a directory of team members), set the level to AUTHENTICATED:

```python
from apps.search.access import SearchAccess

class ArticleCRUDView(CRUDView):
    model = Article
    enable_search = True
    search_fields = ["title", "body"]
    search_access = SearchAccess.AUTHENTICATED
```

### Recipe 3 — per-user row scoping (e.g. "find my own tickets")

When each authenticated user should find only *their own* rows, combine the level with a visibility callback. The callback receives the candidate queryset (already narrowed to FTS-matched ids) and the user; whatever it returns is what the user gets.

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_search = True
    search_fields = ["title", "body", "customer__name"]

    search_access = SearchAccess.AUTHENTICATED
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(owner=user)
    )
```

### Recipe 4 — fully public, anyone can find it

When data is genuinely public (a product catalogue, published posts, a job listing), set the level to ANONYMOUS. Combine with `search_visibility` if you want to expose only a subset of rows (e.g. `published=True`):

```python
class PublishedPostCRUDView(CRUDView):
    model = Post
    enable_search = True
    search_fields = ["title", "body", "tags"]

    search_access = SearchAccess.ANONYMOUS
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(published=True)
    )
```

The callable can be any `(queryset, user) -> queryset` function — a `staticmethod`, a module-level function, a classmethod. If it raises, **the view fails safe**: every hit from that view is dropped for the request rather than leaking unfiltered rows. The exception is logged via `smallstack.search`.

## Walkthrough: building an Inventory app

Suppose you're adding an `inventory` app to a SmallStack project. You have two natural surfaces:

1. **Internal stock management** — only staff should see exact counts, suppliers, cost prices.
2. **Public product catalogue** — anyone (including signed-out visitors) should be able to search products by name, SKU, or description.

That's two CRUDViews on the same model — each with its own `search_access`. Here's the whole pattern.

### The model

```python
# apps/inventory/models.py
from django.db import models
from django.conf import settings


class InventoryItem(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    catalogue_summary = models.CharField(
        max_length=240,
        help_text="The blurb shown to public visitors. Distinct from internal description.",
    )

    # Internal-only fields:
    quantity_on_hand = models.IntegerField(default=0)
    cost_price_cents = models.IntegerField(default=0)
    supplier_notes = models.TextField(blank=True)

    # Publishing controls:
    is_listed = models.BooleanField(
        default=False,
        help_text="When True, the item appears in the public catalogue.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name
```

### The internal CRUDView (staff-only)

The default access level is exactly what you want here. The page lives at `/smallstack/inventory/` and is staff-gated by the CRUDView's own auth mixin; search inherits the same gate via the default `STAFF` level. Every field is searchable — including supplier notes — because staff are the only ones who can find rows.

```python
# apps/inventory/views.py
from apps.smallstack.crud import CRUDView
from .models import InventoryItem


class InventoryAdminCRUDView(CRUDView):
    model = InventoryItem
    url_base = "inventory-admin"
    enable_search = True
    enable_mcp = True   # Claude can search the internal index too — via API token

    search_fields = [
        "name", "sku", "description",
        "supplier_notes",   # ← only staff can find by this; truly internal
    ]
    search_display = "name"
    search_subtitle = "sku"

    # search_access defaults to SearchAccess.STAFF — no explicit setting needed.
```

### The public catalogue CRUDView (anonymous access)

A separate CRUDView, same model. Different name (`inventory-catalogue`), different `search_fields` (only the public-safe ones), and a `search_visibility` callable that scopes results to `is_listed=True` so unpublished items never appear.

```python
# apps/inventory/views.py  (continued)
from apps.search.access import SearchAccess


class InventoryCatalogueCRUDView(CRUDView):
    model = InventoryItem
    url_base = "inventory-catalogue"
    enable_search = True

    # PUBLIC-SAFE FIELDS ONLY — supplier_notes, quantity, cost not searchable here.
    search_fields = ["name", "sku", "catalogue_summary"]
    search_display = "name"
    search_subtitle = "catalogue_summary"

    search_access = SearchAccess.ANONYMOUS
    search_visibility = staticmethod(
        lambda qs, user: qs.filter(is_listed=True)
    )

    # Optional — give the public the MCP tool too, so Claude can power
    # a "what do you sell?" agent against your catalogue.
    enable_mcp = True
```

### What the developer sees

After `make migrations && make migrate && make rebuild_search_index` and a server restart:

```
$ curl http://localhost:8005/search/?q=widget       # anonymous
   → 3 results from "Inventory Item" (catalogue rows only)
   → 1 result from "Help & Docs"
   → 0 from User, APIToken, or the internal Inventory CRUDView

$ curl http://localhost:8005/search/?q=widget  \    # as a signed-in non-staff user
       -b sessionid=...
   → same as above (their access doesn't broaden anything new
     unless you add an AUTHENTICATED-level view)

$ curl http://localhost:8005/search/?q=widget  \    # as staff
       -b sessionid=...
   → full results across every indexed view, including the
     internal InventoryAdminCRUDView with supplier_notes
```

The same model has two faces — staff see everything, anonymous see the published catalogue, and the developer wrote **two CRUDView classes plus four configuration lines**. No middleware, no decorator stack, no API mode. The story is "declare what you want, ship safely."

### Why this works

- **The model owns the data.** Both CRUDViews share `InventoryItem`. There's no duplication.
- **Each surface owns its visibility.** The internal view searches every field; the catalogue view searches only the catalogue-safe ones and filters out unpublished rows.
- **Failures are safe.** A typo in `search_visibility` drops the whole view's hits for that request — never an unfiltered leak.
- **The pattern scales.** Adding a third surface (e.g. an `AUTHENTICATED`-level "members-only" view that includes pricing for signed-in customers) is the same shape: one more CRUDView, one more `search_access`, one more `search_visibility`.

### What's not gated

- **Help docs** (`apps/help/`). Always returned, to every caller — anonymous, authenticated, staff, internal. They are documentation by intent.
- **MCP tools**. The MCP server enforces its own auth (API token + `requires_access` access level). Per-user row visibility within MCP responses is a future improvement; today, MCP search runs with `user=None` (trusted internal).
- **The CRUDView's own list page**. That URL has its own access gate (typically a mixin like `StaffRequiredMixin`). The search gates are a separate, complementary layer.

### Verifying

```bash
uv run python manage.py search_doctor              # registry snapshot
uv run pytest apps/search/tests/test_security.py   # exercises all three levels
```


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
