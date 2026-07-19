# Django SmallStack

*Django that doesn't get in your way. Focus on your idea, not the stack.*

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![Django 6.0](https://img.shields.io/badge/django-6.0-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)
![Version 0.13.4](https://img.shields.io/badge/version-0.13.4-blue)
[![Quality A−](https://img.shields.io/badge/quality-A%E2%88%92-2ea44f)](docs/report-cards/)
![Coverage 80%](https://img.shields.io/badge/coverage-80%25-9acd32)

A small-footprint Django foundation for shipping **web apps, REST APIs, and MCP servers** — with a model-to-three-surfaces pipeline already wired. One model definition. Three production surfaces. No boilerplate.

SQLite by default (scales further than you'd think), no external services required, everything runs on a single machine or container.

📖 **Full docs & guides → [www.smallstack.site](https://www.smallstack.site/)**

---

## The core pattern: One model, three surfaces

Here's the superpower. One `CRUDView` produces an admin web UI, REST endpoints, and MCP tools automatically.

```python
class TicketCRUDView(CRUDView):
    model = Ticket
    actions = [Action.LIST, Action.CREATE, Action.DETAIL, Action.UPDATE, Action.DELETE]
    filter_fields = ["status", "priority", "customer"]
    url_base = "tickets"
    enable_api = True      # → /api/tickets/ (REST + OpenAPI)
    enable_mcp = True      # → list_tickets, create_ticket, … (Claude & agents)
    enable_explorer = True # → /smallstack/explorer/support/ticket/ (HTML admin)
```

Same form validation, same permission logic, three independent surfaces. No code duplication. No "sync the API to match the UI" drudgery. You change the model once; all three surfaces update.

This is the opposite of the typical stack fatigue — instead of bolting REST onto your Django app and MCP onto your REST layer, you declare intent once and let the framework handle the plumbing.

---

## What you get

**The things you don't have to build:**

- **Web admin UI** — CRUD pages with filters, sorting, pagination, dark/light themes (5 color palettes)
- **REST API** — Bearer-token auth, OpenAPI 3.0 with Swagger UI, automatic pagination, filtering
- **MCP server** — JSON-RPC + OAuth + PKCE, works with Claude Desktop and agent frameworks
- **Background tasks** — DB-backed queue (no Redis/Celery to operate)
- **Activity & audit logs** — Request logging with auto-pruning and breakdown stats
- **Search** — Full-text + SQLite FTS or Postgres, with custom ranking and variants for different use cases (SearchBuilder)
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

## Quality & transparency

Every release includes a **quality report card** — a graded scorecard (security, code quality, testing, docs, accessibility) with evidence behind each grade. See **[docs/report-cards/](docs/report-cards/)** for the latest.

Why this matters:
- **Independent** — Produced by a separate testing harness, not self-graded
- **Reproducible** — The rubric and data are public; anyone can re-run it
- **Honest** — Open security issues cap the whole card at F; grades improve over time

---

## What SmallStack is for

✓ Web apps, dashboards, and admin tools  
✓ REST APIs (internal or public)  
✓ MCP servers (Claude, Cursor, other agents)  
✓ Projects where you own or control the database  
✓ Solo developers and small teams  
✓ Fast MVP iteration  
✓ Things that fit on one machine or container

✗ Microservices (SmallStack is monolithic by design)  
✗ Projects that need multiple independent databases  

---

## Learn more

**[www.smallstack.site](https://www.smallstack.site/)** has setup guides, palette details, CRUDView patterns, SearchBuilder examples, MCP setup, and deployment recipes.

Your local `/help/` section (available once running) mirrors the essentials.

---

## License

MIT — use it, modify it, ship it.
