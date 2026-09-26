# CLAUDE.md — SmallStack

You're working inside a Django SmallStack project. This file orients you to the codebase and tells you what to read **before** writing code. The most common AI-built-page failure mode in this codebase is hard-coded colors that look fine on the default palette but break the other four; reading the linked skill files prevents it.

## Read-first skills

When the user asks you to do any of these, read the matching skill file BEFORE writing code:

| If the user wants to… | Read first |
|---|---|
| Build a new page, component, card, table, modal, badge (using SmallStack's theme) | `docs/skills/modern-dark-theme.md` |
| Build/edit any page, form, table, modal, or interactive control — make it **accessible** (a11y / WCAG) | `docs/skills/accessibility.md` |
| Change accent colors — add or tune a color palette | `docs/skills/modify-palettes.md` |
| Ship your own look — Bootstrap / Tailwind / a bespoke base template, alongside ours | `docs/skills/adding-your-own-theme.md` |
| Run any operational task (diagnose, smoke-test, mint, backup, screenshot, deploy) | `docs/skills/cli-tools.md` |
| Create a new Django app with admin pages | `docs/skills/django-apps.md` |
| Add a CRUDView (model → admin + REST + MCP) | `docs/skills/django-apps.md` + `apps/smallstack/docs/building-crud-pages.md` |
| Add keyword search + an MCP search tool to a model | `docs/skills/search.md` |
| Expose a filtered queryset as typed rows/columns for a dashboard/report/chart UI (`@dataset`) | `docs/skills/datasets.md` |
| Add stat cards / metric tiles + drill-down modals to a dashboard page | `docs/skills/dashboard-cards.md` |
| Add a dashboard widget (the central `/smallstack/` dashboard) | `docs/skills/dashboard-widgets.md` |
| Monitor a subsystem's uptime/health on `/smallstack/status/` (Service + Monitor, or a status chart) | `docs/skills/status-monitors.md` |
| Open a maintenance window / SLA-exclude a deploy (`manage.py maintenance`, Kamal hooks) | `docs/skills/status-monitors.md` |
| Test the task queue / heartbeat backend locally (worker + heartbeat harness) | `docs/skills/background-tasks.md` |
| Schedule recurring work (`@scheduled`, cron/interval/once, the scheduler UI + tick) | `docs/skills/scheduler.md` |
| Gate an action on a **human approval** (`@approval_kind`, the decision console, agent-files-human-decides) | `docs/skills/approvals.md` |
| Show a signed-in user an **in-app notification** (topbar bell + inbox, `notify()`) | `docs/skills/notifications.md` |
| **Any integration work** (Zapier/n8n/Slack/Stripe/GitHub/Azure, or SmallStack↔SmallStack) — read this FIRST | `docs/skills/webhooks.md` |
| Notify an external system when a model changes — **outbound webhooks** (`enable_webhooks = True`); shape the payload with `@webhook_transform` | `docs/skills/webhooks.md` |
| Receive/verify an inbound webhook (`@webhook_handler`; provider signatures via `@webhook_verifier`, handshakes via `@webhook_challenge`) | `docs/skills/webhooks.md` |
| **Publish a model as an RSS/Atom feed** (`enable_rss = True`) or a curated `Feed`; enclosures/podcasts via `rss_item_extra` | `docs/skills/rss.md` |
| **Consume an external RSS/Atom feed** into a model on a schedule (`register_feed_source`, the collector) | `docs/skills/rss.md` |
| Expose a model to AI clients via MCP | `docs/skills/mcp/build-mcp-solution.md` |
| Add a custom REST endpoint (non-CRUD) | `docs/skills/custom-api-endpoints.md` |
| Debug a "Swagger is empty" / "MCP can't see my tools" / "weird traffic" report | `docs/skills/api-doctor.md` or `docs/skills/mcp/debug-mcp-failure.md` |
| Take a screenshot to verify UI work | `docs/skills/screenshot-workflow.md` |
| Set up auth or protect a view | `docs/skills/authentication.md` |

The full skill index lives at `docs/skills/README.md`.

## What SmallStack is

A small-footprint Django foundation for shipping four kinds of apps from one codebase:

- **Background tasks** — `django-tasks-db` is pre-wired; `manage.py db_worker` runs queued jobs. One-shot enqueue plus a recurring **`@scheduled`** primitive (`apps/scheduler/`) — DB-backed schedules with a themed `/smallstack/scheduler/` UI, REST + MCP tools, cron/interval/once cadences, and a per-minute tick. See `docs/skills/scheduler.md`.
- **Websites** — themed admin shell, dark mode, palettes, sidebar, breadcrumbs
- **API servers** — REST emitted from CRUDViews; OpenAPI 3.0.3 schema; Swagger UI at `/api/docs/`; ReDoc at `/api/redoc/`
- **MCP servers** — JSON-RPC + OAuth 2.0 + PKCE at `/mcp`; Claude Desktop and Claude.ai Connectors UI work without setup
- **Webhooks** — a foundational integration surface: outbound signed delivery (`enable_webhooks = True`) + inbound receivers (`@webhook_handler`), **four extension seams** (`@webhook_transform`/`@webhook_auth`/`@webhook_verifier`/`@webhook_challenge`) that make Zapier/n8n/Stripe/Slack/Event Grid plug-ins, first-class **SmallStack↔SmallStack** pairing (`sc webhook pair`, loop-safe), stable `event_id` dedupe, `Retry-After` + bulk dead-letter replay; `webhook_doctor`, `sc webhook`

- **Human-in-the-loop approvals** — a generic side-car gate (`apps/approvals/`): apps or AI agents file an `ApprovalRequest` (`@approval_kind` + `request_approval()`), a human decides in the themed console (or the `{% approval_card %}` embed), and the app reacts via per-kind callback, signal, webhook event, or polling. Fan-out to in-app notifications (`apps/notifications/`: topbar bell + inbox) and branded email.

The headline pattern: **one `CRUDView` declaration produces HTML admin pages, REST endpoints, and MCP tools** from a single model. Flip `enable_api = True` / `enable_mcp = True` / `enable_webhooks = True` flags on a CRUDView subclass and the surfaces light up.

## Quick start

```bash
make setup     # uv sync + migrate + create dev superuser (admin/admin)
make run       # dev server on port 8005 (PORT= to change)
```

`make setup` is idempotent. Re-run it anytime.

## Project structure

All custom apps in `apps/`, registered as `apps.<name>`:

- `apps/accounts/` — Custom User model, auth views, login/signup
- `apps/smallstack/` — Theme, CRUDView library, navigation, dashboard, displays, APIToken model — the framework core
- `apps/activity/` — RequestLog middleware and admin
- `apps/approvals/` — Human-in-the-loop approval gate (`@approval_kind` + decision console) at `/smallstack/approvals/requests/`
- `apps/notifications/` — In-app notifications (topbar bell + inbox) at `/smallstack/notifications/`
- `apps/telemetry/` — DB-backed log capture (`LogRecord`) + the `/smallstack/logs/` staff viewer + time-boxed capture windows; `log_capture` / `prune_logs`
- `apps/api/` — `/smallstack/api/` health + activity admin + `api_doctor` command
- `apps/explorer/` — Generic CRUD browser at `/smallstack/explorer/`
- `apps/heartbeat/` — Uptime monitoring + `/status/`
- `apps/help/` — Markdown docs at `/smallstack/help/`
- `apps/mcp/` — MCP JSON-RPC server + OAuth + `/smallstack/mcp/` admin
- `apps/profile/` — UserProfile + theme/palette preferences
- `apps/tasks/` — Background-task helpers
- `apps/tokenmgr/` — Self-service API token UI at `/smallstack/tokens/`
- `apps/usermanager/` — User CRUD at `/smallstack/manage/users/`
- `apps/webhooks/` — Outbound event delivery (`enable_webhooks`) + inbound receivers (`@webhook_handler`) at `/smallstack/webhooks/`
- `apps/website/` — Project-specific pages — **edit freely** (the others are framework-provided)

Settings split in `config/settings/`:
- `smallstack.py` — App-level config (branding, feature flags, palette default, MCP/API toggles)
- `base.py` — Django infrastructure
- `development.py` / `production.py` / `test.py` — environment overrides

## Conventions to follow

- **User model**: `settings.AUTH_USER_MODEL`. Never `from django.contrib.auth.models import User`.
- **Protected views**: `LoginRequiredMixin` or `StaffRequiredMixin` (in `apps/smallstack/mixins.py`).
- **URL namespaces**: `app_name = "<id>"` in `urls.py`, reference as `{% url 'id:name' %}`.
- **Signals**: separate `signals.py`, imported in `apps.py:ready()`.
- **Tests**: `apps/<name>/tests/test_*.py`. `pytest.mark.django_db` when DB is touched.
- **Templates**: extend `smallstack/base.html`. Use `{% load theme_tags %}` for breadcrumbs / nav_active.
- **Types**: prefer strongly typed code where practical — annotate function
  signatures (params + return) on new and edited code; reach for `Any` only
  when the type genuinely can't be expressed. The project typechecks with
  **mypy + django-stubs** over every app (`[tool.mypy]` in `pyproject.toml`;
  migrations/tests excluded, untyped bodies not checked — so annotating a
  function is what opts its body into checking). `make lint` runs ruff **and
  mypy**; both must be green before reporting work done, and the pre-commit
  hook enforces the same gate.

## Theming — the single biggest thing to get right

SmallStack ships **six palettes** (`django`, `dark-blue`, `purple`, `orange`, `high-contrast`, `gold`) × **two themes** (light, dark); the default is `purple`. Users switch them from the user-menu dropdown. **Your code must produce pages that look correct on all 12 combinations.** The authoritative list is `UserProfile.color_palette.choices` + `palettes.css`.

The way to do that is to **never hard-code a color**. Use the CSS variables:

```html
<!-- ❌ AI-built-page killer — locks to legacy warm-gray, brown on orange/django -->
<div style="background: #1e1e1e; border: 1px solid #3a3a3a;">

<!-- ✓ palette-correct -->
<div style="background: var(--card-bg); border: 1px solid var(--card-border);">
```

The variables to know are documented in `docs/skills/modern-dark-theme.md`. The two-second summary: surfaces use `--card-bg`, accent uses `--primary`, hero bands use `--accent-band-bg`, semantic state uses `--success-fg` / `--warning-fg` / `--error-fg`. Tables: use `.table-plain` and let the zebra striping happen automatically.

**Before you write a page, read `docs/skills/modern-dark-theme.md` once. It's ~440 lines but has the prescriptive patterns + named anti-patterns with the actual bugs they caused.** Following it gets pages right on the first try across every palette.

## Tools you'll reach for

All `manage.py` commands run as `uv run python manage.py <name>`. The full reference is `apps/smallstack/docs/cli-reference.md`; the agent's decision tree is `docs/skills/cli-tools.md`.

Most-used:

```bash
make run                                         # dev server (port 8005)
make test                                        # full pytest suite
make lint                                        # ruff check + mypy (the full static gate)
make lint-fix                                    # ruff check --fix
make typecheck                                   # mypy alone
make migrate                                     # apply migrations
make migrations                                  # create new ones
make backup                                      # SQLite snapshot with retention
uv run python manage.py api_doctor               # health-check the REST surface
uv run python manage.py mcp_doctor               # health-check the MCP surface
uv run python manage.py shell                    # shell_plus with auto-imports
uv run python manage.py screenshot_auth          # auth.json for shot-scraper
shot-scraper http://localhost:8005/ -o out.png   # browser screenshot
uv run python manage.py sc ls                    # every CRUDView model (the framework CLI)
uv run python manage.py sc doctor all            # api + mcp + search health in one
```

The **`sc` CLI** (`manage.py sc` / the `sc` shim) is the framework front door for the shell: generic CRUD over any registered CRUDView (`sc ls/get/describe/new/set/rm`, same validation + audit as REST/MCP) plus ops verbs (`doctor/backup/token/status/index`) and `sc commands` discovery. Prefer it over ad-hoc `manage.py shell` snippets — see `docs/skills/sc-cli.md`.

If you find yourself about to write a bash one-liner for "back up the SQLite database" or "validate the OpenAPI spec," **stop and check `docs/skills/cli-tools.md` first**. There's almost certainly a built-in tool for it.

## Visual verification

When you edit UI code, screenshot to verify before reporting done. Pattern (the dev server must be running):

```bash
uv run python manage.py screenshot_auth > /tmp/auth.json
shot-scraper http://localhost:8005/smallstack/your-page/ \
  -o /tmp/check.png --width 1440 --wait 1500 --auth /tmp/auth.json
```

Then read the resulting PNG. Especially valuable for catching contrast issues, layout breaks, and palette-dependent regressions.

To verify across palettes, set the admin user's palette in the shell:

```bash
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username='admin')
u.profile.color_palette = 'orange'   # or 'dark-blue' / 'purple' / 'high-contrast' / 'django'
u.profile.save()"
```

Then screenshot. If the page looks fine on `django` but brown on `orange`, you have hard-coded colors somewhere — that's the bug class the modern-dark-theme skill prevents.

## Don't do these (the anti-patterns)

The biggest recurring mistakes when AI builds pages in this codebase. All of them are addressed in `docs/skills/modern-dark-theme.md`:

1. **Hard-coded hex colors in inline styles or CSS** — `#1e1e1e`, `#3a3a3a`, etc. — lock the page to legacy warm-gray and break every modern palette
2. **`[data-theme="dark"] .my-class { background: #abc; }` overrides** — bypass the palette token system entirely
3. **Inlined `color-mix(in srgb, var(--primary) 15%, var(--body-bg))` recipes** — can't be overridden per palette; use `var(--accent-band-bg)` instead
4. **Manual table zebra striping with `--primary` tints** — accent leaks into every row, competes with data; use `.table-plain` and the striping happens automatically with neutral lift
5. **Hand-rolling backup scripts / OpenAPI validators / token-mint scripts** — there's already a `manage.py` command for it (check `docs/skills/cli-tools.md`)
6. **Importing `django.contrib.auth.models.User` directly** — always `settings.AUTH_USER_MODEL` or `get_user_model()`

## When you're stuck

| Problem | Where to look |
|---|---|
| Page looks brown / muddy on a non-default palette | You hard-coded a color. Grep your page for hex literals. `docs/skills/modern-dark-theme.md` has the variable list. |
| `/api/docs/` is empty | At least one CRUDView needs `enable_api = True`. Run `python manage.py api_doctor --explain`. |
| Claude Desktop can't see MCP tools | Run `python manage.py mcp_doctor`. The Server registry / Orphan files cards point at the fix. |
| New migrations not applying | `make migrate`. Or `python manage.py makemigrations <app>` if you added/changed models. |
| Tests fail because of `Database access not allowed` | Add `pytestmark = pytest.mark.django_db` to the test module. |
| Want to verify in the browser before reporting "done" | `screenshot_auth` + `shot-scraper`. See "Visual verification" above. |

## What's checked into git vs. generated

- ✓ tracked: `apps/`, `config/`, `templates/`, `static/` (your own files), `Makefile`, `pyproject.toml`, `uv.lock`, `docs/skills/`
- ✗ ignored: `.venv/`, `db.sqlite3`, `staticfiles/`, `htmlcov/`, `__pycache__/`, `backups/`

When generating screenshots or working data, write to `/tmp/` so it stays out of the working tree.

## Related docs

- `apps/smallstack/docs/cli-reference.md` — every `manage.py` command + Make target + system tool, with options and examples
- `apps/smallstack/docs/theme-architecture.md` — the color science + variable cascade behind the theme
- `apps/smallstack/docs/api-doctor.md` — the `/smallstack/api/` admin pages
- `apps/smallstack/docs/mcp.md` — Model Context Protocol overview
- `apps/smallstack/docs/building-crud-pages.md` — the CRUDView walkthrough
- `docs/skills/README.md` — the full skill-file index with "before X, read Y" guidance
- `README.md` — repo-level project description (for humans new to SmallStack)
