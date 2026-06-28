# AI Agent Skills

This directory contains reference documentation designed for AI agents (LLMs) working on this codebase. These "skill files" provide structured knowledge about the project's architecture, conventions, and patterns.

## Purpose

When an AI agent is asked to modify or extend this project, these files help it:

- Understand project conventions and patterns
- Follow existing code style and structure
- Make changes that integrate properly with the codebase
- Avoid common mistakes

## Available Skills

| File | Description |
|------|-------------|
| [cli-tools.md](cli-tools.md) | **Start here for "is there a tool for X?"** — task → tool / failure → tool / tool → docs lookup tables |
| [modern-dark-theme.md](modern-dark-theme.md) | **Read before building any page** — canonical patterns, anti-patterns, variable list for the v0.9.x modern-dark theme |
| [modify-palettes.md](modify-palettes.md) | Add a new color palette or tune an existing one — file map, color-science gotchas, verification |
| [search.md](search.md) | Add keyword search + MCP tool to a CRUDView (`enable_search = True`) — FTS5/PG-FTS backend dispatch, RAG via Claude Desktop |
| [django-apps.md](django-apps.md) | Creating apps, CRUDView + tables2 management pages, title bar pattern |
| [building-a-user-facing-site.md](building-a-user-facing-site.md) | **Read for any non-staff user-facing surface** — LoginRequiredMixin + tenancy scoping + SearchAccess for end-user dashboards, "my X" lists, public catalogues |
| [templates.md](templates.md) | Template inheritance, blocks, includes, common patterns |
| [admin-page-styling.md](admin-page-styling.md) | **Definitive UI reference**: buttons, cards, tables, stat cards, action cards, tabs, filter toggles, forms, modals, starter template |
| [theming-system.md](theming-system.md) | CSS variables, palettes, dark mode |
| [adding-your-own-theme.md](adding-your-own-theme.md) | Adding a custom CSS framework alongside SmallStack's built-in theme |
| [theme-scenarios.md](theme-scenarios.md) | Three theme integration scenarios: public-only, user login, or build on SmallStack |
| [authentication.md](authentication.md) | Custom user model, auth views, protecting views |
| [manage-api-tokens.md](manage-api-tokens.md) | Pick the right token surface (/smallstack/tokens/, CLI, OAuth) by question; permissions matrix; reveal-once flow |
| [htmx-patterns.md](htmx-patterns.md) | htmx setup, CSRF, partials, dual-response views, OOB messages |
| [help-documentation.md](help-documentation.md) | Help system, sections, bundled SmallStack docs |
| [settings.md](settings.md) | Split settings, environment variables, feature flags |
| [timezones.md](timezones.md) | Timezone middleware, per-user timezone, localtime_tooltip tag |
| [background-tasks.md](background-tasks.md) | Django Tasks framework with django-tasks-db backend |
| [activity-tracking.md](activity-tracking.md) | HTTP request logging middleware and configuration |
| [logging-audit.md](logging-audit.md) | Logging configuration and audit trail |
| [screenshot-workflow.md](screenshot-workflow.md) | Visual verification with shot-scraper and screenshot_auth |
| [docker-deployment.md](docker-deployment.md) | Docker Compose setup, services, volumes |
| [kamal-deployment.md](kamal-deployment.md) | Kamal deployment configuration, VPS setup, SSL, commands |
| [development-workflow.md](development-workflow.md) | Branching, testing, coverage, documentation, commit style |
| [release-process.md](release-process.md) | Versioning, release checklist, GitHub releases |
| [integration-workflow.md](integration-workflow.md) | Pulling upstream into downstream projects, deploying |
| [downstream-release-migration.md](downstream-release-migration.md) | Migrating a downstream onto a new release — additive vs breaking changes, the false-test-result + removed-symbol traps, this release's actions |
| [api-discovery.md](api-discovery.md) | API discovery endpoints: schema introspection, OpenAPI spec, OPTIONS metadata |
| [custom-api-endpoints.md](custom-api-endpoints.md) | Building non-CRUD API endpoints with the `@api_view` decorator |
| [api-doctor.md](api-doctor.md) | Debug API setup + threat signals via `/smallstack/api/` (Health + Activity) and `python manage.py api_doctor` |
| [dashboard-cards.md](dashboard-cards.md) | **The stat-card standard**: the `{% stat_card %}` tag, the global drill-down modal, and the `render_stat_list` helper for the metric tiles atop dashboard pages |
| [dashboard-widgets.md](dashboard-widgets.md) | Dashboard widget protocol: `DashboardWidget` class, Explorer vs standalone registration, data layer, REST API |
| [status-monitors.md](status-monitors.md) | **The status/uptime monitoring standard**: register a `Service` + `Monitor` (cheap `check()`), the 3-tier taxonomy (Site / Site Monitors / External), the branded public `/status/` page (90-day timelines + maintenance calendar), per-monitor public flag + independent SLA/maintenance, the no-code Add-monitor wizard, and pluggable `Visualization` panels |
| [card-displays.md](card-displays.md) | Card grid displays: `CardDisplay` (key-value), `AvatarCardDisplay`, authoring new card variants |
| [calendar-displays.md](calendar-displays.md) | Month-grid calendar display: `CalendarDisplay` config, ranged vs single-date events, month navigation |
| [update-docs-and-skills.md](update-docs-and-skills.md) | File group map for updating docs/skills after code changes |

### MCP (Model Context Protocol)

| File | Description |
|------|-------------|
| [mcp/enable-mcp-for-a-model.md](mcp/enable-mcp-for-a-model.md) | Opt a CRUDView into MCP via `enable_mcp = True` |
| [mcp/end-user-tools.md](mcp/end-user-tools.md) | **Read for non-staff MCP** — `LoginRequiredMixin` + `get_list_queryset` tenancy + `search_access`/`search_visibility` so Alice's token sees only Alice's data |
| [mcp/write-a-custom-tool.md](mcp/write-a-custom-tool.md) | Add cross-cutting tools with the `@tool` decorator + `current_context()` |
| [mcp/add-a-write-tool.md](mcp/add-a-write-tool.md) | Expose create/update/delete via factory vs custom write tools |
| [mcp/connect-claude-desktop.md](mcp/connect-claude-desktop.md) | Connect Claude Desktop / Claude.ai Connectors UI to the server |
| [mcp/debug-mcp-failure.md](mcp/debug-mcp-failure.md) | Decision tree for diagnosing connector failures |
| [mcp/add-mcp-to-this-project.md](mcp/add-mcp-to-this-project.md) | Bootstrap MCP in a fresh / non-MCP-aware project |
| [mcp/extend-explorer-for-tokens.md](mcp/extend-explorer-for-tokens.md) | Surface APIToken management via Explorer |
| [mcp/mcp-admin-pages.md](mcp/mcp-admin-pages.md) | Use the `/smallstack/mcp/` Health / Tools / Activity admin pages from a debugging session |
| [mcp/build-mcp-solution.md](mcp/build-mcp-solution.md) | "User wants Claude to do X" → decision tree for CRUDView vs `@tool` + copy-pasteable patterns. Start here when designing new MCP features. |
| [mcp/verify-mcp.md](mcp/verify-mcp.md) | Consolidated verify checklist: doctor, --explain, make mcp-test, admin pages, dashboard widget, Claude Desktop — picks the right path per question |
| [mcp/configure-mcp.md](mcp/configure-mcp.md) | Scenario → `MCP_*` setting map: turn off OAuth, custom theme, kamal-proxy, multi-tenant, verbose logging, autodiscover |

### Database & PostgreSQL

| File | Description |
|------|-------------|
| [database.md](database.md) | Database overview — SQLite default + tuning (WAL/IMMEDIATE), backups, when to switch, SQLite→Postgres data migration |
| [postgres/setup-local.md](postgres/setup-local.md) | Switch a project to Postgres locally — Docker server, `psycopg` extra, `DATABASES` config, FTS auto-provision on migrate |
| [postgres/production.md](postgres/production.md) | Postgres in production — driver in the image, `DATABASE_URL`, `CONN_MAX_AGE`/PgBouncer, Kamal accessory, managed services, deploy-time search backfill, `pg_dump` backups (NOT `make backup`) |
| [postgres/testing.md](postgres/testing.md) | Run the suite on Postgres — `TEST_DB=postgres` switch, the `--extra postgres` gotcha (`make test` can't), expected skip deltas, CI matrix |
| [postgres/sqlite-vs-postgres.md](postgres/sqlite-vs-postgres.md) | **Read before search/migration/SQL work** — FTS self-provisioning, hyphen tokenization, `varchar` enforcement, query ordering, the "green on SQLite, red on Postgres" checklist |

## Usage

AI agents should read relevant skill files before making changes to the corresponding parts of the codebase. For example:

- **Before running ANY operational command** (diagnose, smoke-test, mint token, backup, screenshot, deploy) → read `cli-tools.md` first
- Before creating a new app → read `django-apps.md`
- Before creating templates → read `templates.md`
- Before building any admin/management page → read `admin-page-styling.md` (buttons, cards, tables, forms, etc.)
- **Before building ANY new page or component → read `modern-dark-theme.md` first** (the v0.9.x canonical patterns supersede earlier guides)
- Before adding a new color palette → read `modify-palettes.md`
- Before adding `enable_search = True` to a CRUDView (or building any search-shaped feature) → read `search.md`
- Before switching a project to PostgreSQL (local, production, or testing) → read `postgres/setup-local.md`, `postgres/production.md`, or `postgres/testing.md`
- **Before search / data-migration / raw-SQL work that must run on both engines → read `postgres/sqlite-vs-postgres.md`** (the SQLite-passes-Postgres-fails gotchas)
- Before modifying CSS/theming → read `theming-system.md` for the variable cascade, then `modern-dark-theme.md` for current patterns
- Before building a new page that should fit the SmallStack theme → read `modern-dark-theme.md` (the canonical patterns)
- Before adding a custom theme (Bootstrap, Tailwind, etc.) → read `adding-your-own-theme.md`
- Before deciding which theme approach to take → read `theme-scenarios.md`
- Before working with auth → read `authentication.md`
- Before answering an API-token question (mint, revoke, where to look) → read `manage-api-tokens.md`
- Before adding htmx interactions → read `htmx-patterns.md`
- Before adding a help page → read `help-documentation.md`
- Before changing settings → read `settings.md`
- Before adding background tasks → read `background-tasks.md`
- Before working with activity tracking → read `activity-tracking.md`
- Before taking screenshots → read `screenshot-workflow.md`
- Before deploying with Docker → read `docker-deployment.md`
- Before deploying with Kamal → read `kamal-deployment.md`
- Before developing features → read `development-workflow.md`
- Before releasing a version → read `release-process.md`
- Before pulling upstream into downstream → read `integration-workflow.md`
- Before migrating a downstream across one or more releases → read `downstream-release-migration.md`
- Before integrating with the SmallStack API → read `api-discovery.md`
- Before building custom (non-CRUD) API endpoints → read `custom-api-endpoints.md`
- Before debugging an API setup, an empty Swagger, or a "weird traffic" report → read `api-doctor.md`
- Before adding stat cards / metric tiles + drill-down modals to a dashboard page → read `dashboard-cards.md`
- Before adding dashboard widgets (the `/smallstack/` central dashboard data protocol) → read `dashboard-widgets.md`
- Before monitoring a subsystem's uptime/health (a `Service` + `Monitor`), exposing a health check on `/smallstack/status/`, or adding a status visualization → read `status-monitors.md`
- Before configuring or building card-grid list displays → read `card-displays.md`
- Before adding a month-grid calendar to a model → read `calendar-displays.md`
- Before updating docs after code changes → read `update-docs-and-skills.md`
- **Before designing any MCP feature** → read `mcp/build-mcp-solution.md` (decision tree + patterns)
- Before exposing a CRUDView to AI clients → read `mcp/enable-mcp-for-a-model.md`
- Before adding a custom MCP tool → read `mcp/write-a-custom-tool.md`
- Before changing any `MCP_*` setting → read `mcp/configure-mcp.md`
- Before saying "MCP works" → read `mcp/verify-mcp.md`
- Before debugging an MCP failure → read `mcp/debug-mcp-failure.md`

## Common combinations

Multi-skill recipes for the headline use cases. Each row is "pick this combination, read these files in this order."

| Goal | Read in this order |
|---|---|
| **Model → web admin + REST + MCP + Search in one class** (the headline pipeline) | `crud-views.md` → `enable-mcp-for-a-model.md` → `search.md` → `api-discovery.md` |
| **End-user CRUD** (Alice signs in and sees only her stuff, on web + REST + MCP) | `building-a-user-facing-site.md` → `mcp/end-user-tools.md` → `crud-views.md` (for `get_list_queryset` + `can_update`/`can_delete`) |
| **Public catalogue** (anonymous visitors can browse + search published rows) | `building-a-user-facing-site.md` (Recipe 4) → `search.md` (Inventory walkthrough, "Recipe 4") |
| **AI/RAG over a custom model** (Claude searches your tickets, finds rows, answers with citations) | `search.md` → `mcp/build-mcp-solution.md` → `mcp/enable-mcp-for-a-model.md` → `mcp/connect-claude-desktop.md` |
| **Both staff + end-user views of the same model** (operator console + customer portal on `Invoice`) | `crud-views.md` (two CRUDView classes on one model, different `url_base`) → `building-a-user-facing-site.md` (the user-facing class) → `search.md` ("Walkthrough: building an Inventory app") |
| **Custom non-CRUD tool** (a "send-email" or "regenerate-report" MCP/REST action) | `custom-api-endpoints.md` (for REST) → `mcp/write-a-custom-tool.md` (for MCP) → `mcp/enable-mcp-for-a-model.md` (for the auth model) |
| **OAuth-issued tokens via the Connectors UI** (Claude Desktop calling your CRUDView) | `mcp/connect-claude-desktop.md` → `mcp/enable-mcp-for-a-model.md` → `mcp/verify-mcp.md` |
| **Theme-correct page across all five palettes** (your custom landing page that doesn't break on `orange`) | `modern-dark-theme.md` → `screenshot-workflow.md` (for the palette-cycle verification) |
| **Add clickable metric tiles + drill-down modals** (the stat cards atop an app's own dashboard page) | `dashboard-cards.md` → `htmx-patterns.md` (for the partial-response endpoint) |
| **Add a per-model dashboard widget** (a tile on the central `/smallstack/` dashboard that summarises your data) | `dashboard-widgets.md` → `crud-views.md` (for `get_list_queryset` if the widget should respect tenancy) |
| **Monitor a subsystem's uptime/health** (a `Service` + `Monitor` on `/smallstack/status/`, or a new status chart) | `status-monitors.md` → `modern-dark-theme.md` (for visualization partial colors) |
| **Recurring/scheduled job** (today: cron + management command; v0.12.0: `@scheduled` primitive) | `background-tasks.md` (read the "no recurring primitive yet" note) |

If a goal isn't covered here yet, the canonical decision tree is in `mcp/build-mcp-solution.md` for AI-touching features, or `from-zero-to-running.md` for project-shape questions.

## For Humans

These files are also useful for developers new to the project. They provide quick references for:

- Understanding how different systems work
- Following established patterns
- Finding the right files to modify

## Contributing

When adding significant new features or systems to the project, consider creating a corresponding skill file to document:

- File locations and structure
- Key concepts and patterns
- Step-by-step procedures
- Configuration options
- Best practices
