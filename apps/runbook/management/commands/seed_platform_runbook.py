"""Seed the Runbook app with the "Platform Access Guide" runbook.

Documents how to drive SmallStack models through all four programmatic
surfaces — the `sc` CLI, the REST API, MCP, and search — with copy-pasteable
examples. Idempotent: re-running skips documents that already exist.

    uv run python manage.py seed_platform_runbook
"""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.runbook.models import Document, Runbook, Section

User = get_user_model()

# ---------------------------------------------------------------------------
# Document content
# ---------------------------------------------------------------------------

OVERVIEW_MD = """---
title: The Four Surfaces
---

# The Four Surfaces

SmallStack's headline idea: **one `CRUDView` declaration lights up four
programmatic surfaces from a single model** — HTML admin pages, a REST API,
MCP tools, and keyword search. You write the model and a small view class; the
framework emits the rest.

## One declaration, four surfaces

```python
# apps/support/views.py
from apps.smallstack.crud import CRUDView, Action

class TicketCRUDView(CRUDView):
    model = Ticket
    url_base = "support/tickets"          # → /api/support/tickets/ and tool nouns
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]

    enable_api = True                      # REST endpoints
    enable_mcp = True                      # MCP tools
    enable_search = True                   # keyword search
    search_fields = ["title", "description", "customer__name"]
    filter_fields = ["status", "priority"]
    ordering_fields = ["created_at", "priority"]
```

That single class produces:

| Surface | What you get |
|---------|--------------|
| **CLI** (`sc`) | `sc ls tickets`, `sc get ticket 4`, `sc new ticket …` — always available for every registered model |
| **REST API** | `GET/POST /api/support/tickets/`, `GET/PUT/PATCH/DELETE /api/support/tickets/<id>/` |
| **MCP** | `list_tickets`, `get_ticket`, `create_ticket`, `update_ticket`, `delete_ticket` |
| **Search** | `search_tickets` (MCP), `?q=` on the REST list, the omnibar, and `sc search` |

> note: The **CLI works for every registered model with no flags at all** — it is
> the universal read/write skin. The `enable_api` / `enable_mcp` / `enable_search`
> flags only gate the REST, MCP, and search surfaces.

## The same code path everywhere

All four surfaces share one implementation for search, filtering, ordering,
serialization, validation (the model's `form_class`), and the audit log. A write
made from the CLI is validated and audited exactly like a write from REST or MCP —
the transport differs, the behavior does not. So an example you learn in one
surface transfers directly to the others.

## Health-check every surface at once

```bash
uv run python manage.py sc doctor all      # api + mcp + search in one report
uv run python manage.py sc ls              # every registered model + its flags
```

`sc ls` with no arguments is your table of contents: each row shows the model and
three flag columns — `a` (api), `m` (mcp), `s` (search) — so you can see at a
glance what is exposed where.

## Where to go next

- **CLI** — the fastest way to inspect and edit any model from a shell
- **REST API** — HTTP + bearer tokens for scripts and services
- **MCP** — let Claude Desktop / Claude.ai read and write your models
- **Search** — one query across every indexed model
"""

CLI_MD = """---
title: Using the sc CLI
---

# Using the `sc` CLI

`sc` is SmallStack's framework CLI — a git-style command over the CRUDView
registry plus a set of ops verbs. It is a thin skin over the **same** validation
and audit path as REST and MCP, so it is the fastest way to inspect or edit any
model without writing a shell snippet.

## Invocation

```bash
uv run python manage.py sc <verb> …     # always works
sc <verb> …                             # shorter, via the console-script shim
```

## Discover what exists

```bash
sc ls                       # every registered model + flags (a=api m=mcp s=search)
sc ls --counts              # add a live row count per model
sc describe user            # fields, search/filter fields, actions, flags
sc describe monitoredendpoint --json | jq '.write_fields'
```

Models are addressed by a **case-insensitive token**: model name (`user`),
`app.model` (`accounts.user`), verbose name, or the view's `url_base`. A miss
prints "did you mean…" suggestions.

## Read

```bash
sc get user 3                                   # one object's detail fields
sc get user 3 --json | jq '.email'

sc ls user -q alice --order -date_joined --limit 20
sc ls monitoredendpoint --filter enabled=true --json
sc search "acme"                                # cross-model, ranked
```

`-q` searches the view's `search_fields`; `--filter key=value` accepts only the
view's `filter_fields`; `--order field` (prefix `-` for descending) accepts only
`ordering_fields`. Add `--user alice` to scope reads through the view's tenancy
hook **as that user**.

## Write

Writes validate through the model's `form_class` and record an audit entry
tagged `CLI`. Staff-gated models require `--user <staff-username>`.

```bash
sc new monitoredendpoint \\
   --name "Homepage" --slug home --method GET \\
   --url https://example.com --expected_status 200 \\
   --timeout_seconds 10 --user admin

# large text fields via stdin or a file
echo "$LONG_BODY" | sc new note --title Report --stdin-field=body --user admin

sc set monitoredendpoint 5 --enabled=false --user admin   # PATCH-merge
sc rm  monitoredendpoint 5 --force --user admin           # --force is required
```

Every write verb accepts `--json` to emit the resulting object.

## Ops verbs

```bash
sc doctor all                       # api + mcp + search health (--check-only for CI)
sc backup                           # atomic SQLite snapshot with retention
sc backup --keep 30
sc token create alice --name "CI key" --access-level readonly
sc token list --all --json
sc token revoke <prefix>
sc status check                     # run one heartbeat sweep now
sc status maintenance open --minutes 15 --title "Deploy v1.2"
sc index rebuild --all              # rebuild the search index
sc commands                         # discover every framework management command
```

> note: `--user` matters for two reasons: it sets the **audit actor** and it
> enforces **staff gating**. Without it the CLI acts as an unscoped local admin,
> like `manage.py shell`.

## Why reach for it

Prefer `sc` over ad-hoc `manage.py shell` snippets: same validation, same audit
trail, machine-readable `--json`, and it composes with `jq` in scripts.
"""

API_MD = """---
title: Using the REST API
---

# Using the REST API

Any CRUDView with `enable_api = True` emits a REST resource under `/api/`. The
schema, docs, and auth are wired up for you.

## Endpoints for a model

For a view with `url_base = "status/endpoints"`:

```
GET    /api/status/endpoints/            # list  (?q= &<filter>= &ordering= &page= &page_size=)
POST   /api/status/endpoints/            # create
GET    /api/status/endpoints/<id>/       # detail
PUT    /api/status/endpoints/<id>/       # full update
PATCH  /api/status/endpoints/<id>/       # partial update
DELETE /api/status/endpoints/<id>/       # delete
```

Which verbs appear depends on the view's `actions`.

## Explore the surface

```
/api/docs/               # Swagger UI (try requests in the browser)
/api/redoc/              # ReDoc
/api/schema/openapi.json # OpenAPI 3.0.3 spec
```

```bash
uv run python manage.py api_doctor --explain   # list every generated endpoint
```

## Authenticate

Mint a bearer token, then send it on every request.

```bash
# 1. Exchange username + password for a token
TOKEN=$(curl -s -X POST http://localhost:8005/api/auth/token/ \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"admin"}' | jq -r .token)

# 2. Use it
curl http://localhost:8005/api/status/endpoints/ \\
  -H "Authorization: Bearer $TOKEN"
```

You can also mint tokens without a password round-trip:

```bash
sc token create admin --name "CI key" --access-level readonly
# or: uv run python manage.py create_api_token --user admin --name "CI key"
```

Access levels: `readonly` (GET only), `staff` (staff-gated models), `auth` (the
`/api/auth/users/…` admin endpoints).

## Full example

```bash
# create
curl -X POST http://localhost:8005/api/status/endpoints/ \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"name":"API Health","slug":"api-health","service":"api",
       "url":"https://api.example.com/health/","method":"GET",
       "expected_status":200,"timeout_seconds":10,"enabled":true,"public":false}'

# list with search + filter + ordering + pagination
curl "http://localhost:8005/api/status/endpoints/?q=health&enabled=true&ordering=-created_at&page_size=50" \\
  -H "Authorization: Bearer $TOKEN"

# partial update
curl -X PATCH http://localhost:8005/api/status/endpoints/5/ \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"enabled":false}'
```

## Built-in auth endpoints

```
POST /api/auth/token/                 # mint (username + password)
POST /api/auth/token/refresh/         # refresh a login token
GET  /api/auth/me/                    # current user
POST /api/auth/logout/                # revoke the token
GET  /api/auth/users/                 # list users        (auth-level token)
POST /api/auth/users/<id>/password/   # reset a password  (auth-level token)
```

> note: List query params are shared with the CLI and MCP: `?q=` searches
> `search_fields`, each `filter_fields` name becomes a query param, and
> `ordering=` takes a comma-separated list (prefix `-` for descending).
"""

MCP_MD = """---
title: Using MCP
---

# Using MCP

MCP (Model Context Protocol) lets AI clients — Claude Desktop and the Claude.ai
Connectors UI — read and write your models as **tools**. Any CRUDView with
`enable_mcp = True` is exposed automatically; no per-tool wiring.

## Generated tools

For a view with `url_base = "status/endpoints"` on the `MonitoredEndpoint`
model, five tools appear:

```
list_status_endpoints(q, service, enabled, public, method, ordering, limit)
get_monitored_endpoint(pk)
create_monitored_endpoint(name, slug, service, url, method, expected_status, …)
update_monitored_endpoint(pk, …)
delete_monitored_endpoint(pk)
```

Naming: `list_<plural>` uses the plural noun; `get/create/update/delete_<singular>`
use the singular. Override the noun with `mcp_singular` / `mcp_plural` on the
view. Create/update/delete are gated behind write access, and staff-only views
require a staff-level token.

## Search tools (always on)

The search app registers cross-cutting tools regardless of per-model flags:

```
search_all(query, limit_per_model)     # every indexed model at once
search_users(query, limit)             # one per searchable model
search_api_tokens(query, limit)
search_help(query, limit)              # the bundled docs at /smallstack/help/
```

## Connect a client

The endpoint is `POST /mcp` (OAuth 2.0 + PKCE). In Claude Desktop or the
Claude.ai Connectors UI, add a connector pointing at:

```
https://<your-host>/mcp
```

The client auto-discovers OAuth via `/.well-known/oauth-authorization-server`,
performs dynamic client registration, and walks you through login + approval.
Local development works the same against `http://localhost:8005/mcp`.

## Health-check

```bash
uv run python manage.py mcp_doctor          # registry, tools, access control, OAuth
uv run python manage.py sc doctor mcp
```

`mcp_doctor` flags the two classic failures: a view that forgot `enable_mcp`, and
orphaned tool files with no matching view.

> note: MCP and REST share serialization, filtering, and the audit log. A tool
> call is validated through the same `form_class` and recorded the same way as an
> equivalent REST call — the only difference is the transport and the auth handshake.

## Example prompts once connected

- "List the status endpoints that are disabled." → `list_status_endpoints(enabled=false)`
- "Create a monitor for https://example.com/health." → `create_monitored_endpoint(…)`
- "Find anything about the acme customer." → `search_all(query="acme")`
- "How do I add a color palette?" → `search_help(query="add a palette")`
"""

SEARCH_MD = """---
title: Searching Models
---

# Searching Models

Opt a model into keyword search and it becomes findable from five places at
once: the omnibar, the search page, the REST list, an MCP tool, and `sc search`.

## Opt in

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    enable_search = True
    search_fields = ["title", "description", "customer__name"]
    search_display = "title"           # the result-row heading
    search_subtitle = "description"    # truncated preview under it
    search_weight = {                  # higher = ranked higher
        "title": 3,
        "customer__name": 2,
        "description": 1,
    }
```

The backend is chosen automatically: **SQLite FTS5** (BM25 + porter stemming) or
**Postgres full-text** (a self-provisioned `search_vector` + GIN index). Neither
needs manual setup — the index is provisioned on the next migrate.

## Backfill existing rows

If rows existed before you opted in, build the index once:

```bash
uv run python manage.py rebuild_search_index support.Ticket
uv run python manage.py rebuild_search_index --all
uv run python manage.py sc index rebuild --all      # same thing via sc
```

## Query it — five surfaces

```bash
# CLI — cross-model, ranked
sc search "acme"
sc search "acme" --limit 20 --user alice --json

# CLI — one model
sc ls user -q alice
```

```
# REST — the ?q= param on any searchable model's list
GET /api/manage/users/?q=alice

# MCP — search_all(query="alice")  or  search_users(query="alice")

# UI — the search page
/smallstack/search/?q=alice

# UI — the omnibar (Ctrl/Cmd-K), JSON-backed at
/smallstack/search/omnibar/?q=alice
```

## Health-check

```bash
uv run python manage.py search_doctor --explain   # indexed models + MCP tools
uv run python manage.py search_doctor --audit     # access tiers + visibility
uv run python manage.py sc doctor search
```

## Currently indexed in this project

| Model | Fields | MCP tool |
|-------|--------|----------|
| `User` | username, email, first/last name | `search_users` |
| `APIToken` | name, prefix | `search_api_tokens` |

Plus `search_all` (everything) and `search_help` (the bundled docs).

> note: All five surfaces enforce the same access tiers (staff / authenticated /
> anonymous) and per-model visibility callbacks — search never leaks a row a
> surface wouldn't otherwise show.
"""


# ---------------------------------------------------------------------------
# Seeder
# ---------------------------------------------------------------------------

# (title, section-slug, markdown, filename)
DOCS = [
    ("The Four Surfaces", "overview", OVERVIEW_MD, "the-four-surfaces.md"),
    ("Using the sc CLI", "cli", CLI_MD, "using-the-sc-cli.md"),
    ("Using the REST API", "rest-api", API_MD, "using-the-rest-api.md"),
    ("Using MCP", "mcp", MCP_MD, "using-mcp.md"),
    ("Searching Models", "search", SEARCH_MD, "searching-models.md"),
]

SECTIONS = [
    ("Overview", "overview", "How one CRUDView lights up four surfaces", 0),
    ("CLI", "cli", "Drive any model from a shell with sc", 1),
    ("REST API", "rest-api", "HTTP + bearer tokens for scripts and services", 2),
    ("MCP", "mcp", "Expose models to Claude Desktop and Claude.ai", 3),
    ("Search", "search", "One query across every indexed model", 4),
]


class Command(BaseCommand):
    help = "Seed the 'Platform Access Guide' runbook (CLI / API / MCP / search how-to)."

    def handle(self, *args: Any, **options: Any) -> None:
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            self.stderr.write("No superuser found. Run `make setup` first.")
            return

        runbook, created = Runbook.objects.get_or_create(
            slug="platform-access",
            defaults={
                "name": "Platform Access Guide",
                "description": (
                    "How to drive SmallStack models through the CLI, REST API, MCP, "
                    "and search — with copy-pasteable examples."
                ),
                "icon": "book",
                "is_public": True,
            },
        )
        self.stdout.write(f"  {'Created' if created else 'Exists'}: Runbook '{runbook.name}'")

        sections = {}
        for name, slug, desc, order in SECTIONS:
            section, created = Section.objects.get_or_create(
                slug=slug,
                runbook=runbook,
                defaults={"name": name, "description": desc, "order": order},
            )
            sections[slug] = section
            self.stdout.write(f"  {'Created' if created else 'Exists'}: Section '{name}'")

        for title, section_slug, content, filename in DOCS:
            section = sections[section_slug]
            if Document.objects.filter(title=title, section=section, is_archived=False).exists():
                self.stdout.write(f"  Exists: Document '{title}'")
                continue
            doc = Document(
                title=title,
                runbook=section.runbook,
                section=section,
                key=slugify(title),
                description=f"{title} — programmatic access guide",
                created_by=user,
                via="web",
            )
            doc.save()
            doc.create_new_version(
                file=SimpleUploadedFile(filename, content.encode("utf-8")),
                created_by=user,
                via="web",
            )
            self.stdout.write(f"  Created: Document '{title}'")

        self.stdout.write(self.style.SUCCESS("\nPlatform Access Guide runbook seeded."))
