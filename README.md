# Django SmallStack

*Django that doesn't get in your way. Focus on your idea, not the stack.*

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![Django 6.0](https://img.shields.io/badge/django-6.0-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)
![Version 0.13.4](https://img.shields.io/badge/version-0.13.4-blue)
[![Quality A−](https://img.shields.io/badge/quality-A%E2%88%92-2ea44f)](docs/report-cards/)
![Coverage 80%](https://img.shields.io/badge/coverage-80%25-9acd32)

A small-footprint Django foundation for shipping **web apps, REST APIs, MCP servers, search interfaces, and CLI tools** — with a model-to-five-surfaces pipeline already wired. One model definition. Five production surfaces. No boilerplate.

SQLite by default (scales further than you'd think), no external services required, everything runs on a single machine or container.

📖 **Full docs & guides → [www.smallstack.site](https://www.smallstack.site/)**

---

## Five surfaces from one declaration

A `CRUDView` bound to a model derives CRUD tools automatically, then exposes them on the surfaces you opt into. One model. One view. Five independent outputs.

```python
# apps/tickets/views.py
class TicketCRUDView(CRUDView):
    model = Ticket
    list_columns = ["id", "title", "status"]
    enable_api = True      # → REST + OpenAPI
    enable_mcp = True      # → Claude tools
    enable_search = True   # → full-text search
```

This generates:

**→ HTML** (`/tickets/`)  
CRUD pages with htmx tabs, filters, sorting, pagination. Dark/light themes (5 color palettes).

**→ REST API** (`/api/tickets/`)  
REST endpoints with bearer-token auth, OpenAPI 3.0 spec, automatic pagination and filtering.

**→ MCP Server** (`/mcp`)  
JSON-RPC tools `tickets_list`, `tickets_get`, `tickets_create`, etc. — ready for Claude Desktop and agent frameworks.

**→ Search Interface** (`/search/`)  
Full-text search page + `search_tickets` MCP tool for retrieval (RAG pipelines).

**→ CLI** (`sc tickets`)  
Terminal CRUD: `sc ls`, `sc get`, `sc search`, staff-gated `sc new/set/rm`. `--json` on everything.

Same form validation, same permission logic, all five surfaces. You change the model once; all five update automatically. No "keep the API in sync with the UI" drudgery.

---

## What you get

**The things you don't have to build:**

- **Web CRUD UI** — HTML pages with htmx interactions, filters, sorting, pagination, dark/light themes (5 color palettes)
- **REST API** — Bearer-token auth, OpenAPI 3.0 with Swagger UI, automatic pagination, filtering
- **MCP server** — JSON-RPC + OAuth + PKCE, works with Claude Desktop and agent frameworks
- **Full-text search** — SQLite FTS or Postgres SearchVector, with custom ranking and variants (SearchBuilder)
- **CLI tool** — Terminal CRUD operations with `--json` output, staff-gated writes
- **Background tasks & scheduler** — DB-backed queue (no Redis/Celery to operate) plus a `@scheduled` recurring-job scheduler with a themed UI, REST + MCP surfaces, and cron/interval/once cadences
- **Activity & audit logs** — Request logging with auto-pruning and breakdown stats
- **Auth** — Custom User model, photo, timezone, theme preference, token management
- **Health monitoring** — Uptime monitoring, status page, API/MCP health dashboards
- **Docs & help system** — Bundled markdown docs with images, versioning, and search

All of these run themselves. You don't configure them; they're just there.

---

## For AI-assisted development

SmallStack is built around the vibe-coding workflow. When you open Claude Code or Cursor:

**`CLAUDE.md`** — Orients the AI to your codebase and lists the essential skills per task type. The AI knows where to look and what patterns to follow.

**`docs/skills/`** — A library of reference guides covering the full stack:
- Modern dark theme (how to build pages that work across all 5 palettes on the first try)
- CRUDView patterns and configuration
- SearchBuilder (custom variants, computed fields, ranking)
- MCP tool authoring
- API conventions and client generation
- CLI patterns
- Deployment playbooks

The depth is real — 40+ skill files covering everything from "add a new model" to "deploy to production" — but they're organized so the AI finds the right one for the task at hand.

**Result:** You spend your mental energy on your app's logic, not wrestling with framework conventions or cargo-culting from Stack Overflow.

---

## Quick start

**Prerequisites:** [uv](https://docs.astral.sh/uv/) (manages Python automatically, no system Python needed) and `make`.

```bash
# Install uv if you don't have it:
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
# Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Clone and bootstrap:
git clone https://github.com/emichaud/django-smallstack.git myapp
cd myapp
make setup    # uv sync + migrate + create dev superuser (admin/admin)
make run      # dev server on port 8005
```

Open http://localhost:8005, log in with `admin` / `admin`. The `/help/` section has the rest.

**Docker:** `cp .env.example .env && docker compose up -d` (port 8010).

---

## Modern dark theme

Five color palettes × two themes (light/dark) — switchable from the user menu. The default near-black aesthetic with vibrant Tailwind-style accents works in any light. Build pages that look correct across all 5 automatically.

<p>
  <img src="apps/smallstack/docs/images/smallstack-docs.png" alt="Help System Dark Mode" width="49%">
  <img src="apps/smallstack/docs/images/smallstack-docs-light.png" alt="Help System Light Mode" width="49%">
</p>

---

## Development

```bash
make test          # pytest with coverage
make lint          # ruff check
make lint-fix      # ruff check --fix
make api-test      # REST API smoke test
make mcp-test      # MCP server smoke test
```

---

## What SmallStack is for

| Use Case | Fit |
|----------|-----|
| Full web applications | ✓ Sweet spot |
| Internal business tools | ✓ Sweet spot |
| Automation & background jobs | ✓ Sweet spot |
| Data-driven business apps | ✓ Sweet spot |
| Backend API servers | ✓ Capable |
| Content management systems | ✓ Capable |
| ML & data science workflows | ✓ Capable |
| SaaS platforms | ✗ Not the best fit |
| E-commerce | ✗ Not the best fit |
| High-traffic platforms (>1000 req/s) | ✗ Not the best fit |

**In short:** SmallStack shines for solo developers and small teams building web apps, internal tools, and APIs. It's not designed for microservices (monolithic by nature) or high-scale platforms (single-machine focused).

---

## Quality & transparency

Every release includes a **quality report card** — a graded scorecard (security, code quality, testing, docs, accessibility) with evidence behind each grade. See **[docs/report-cards/](docs/report-cards/)** for the latest.

Why this matters:
- **Independent** — Produced by a separate testing harness, not self-graded
- **Reproducible** — The rubric and data are public; anyone can re-run it
- **Honest** — Open security issues cap the whole card at F; grades improve over time

---

## Learn more

**[www.smallstack.site](https://www.smallstack.site/)** has setup guides, palette details, CRUDView patterns, SearchBuilder examples, MCP setup, and deployment recipes.

Your local `/help/` section (available once running) mirrors the essentials.

---

## License

MIT — use it, modify it, ship it.
