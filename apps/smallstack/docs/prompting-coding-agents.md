---
title: Prompting a coding agent
description: Copy-ready prompts for the common getting-started tasks — phrased so the agent uses what SmallStack already provides
---

# Prompting a coding agent

{{ project_name }} is built to be extended by an AI coding agent — Claude Code, Codex, Cursor, Copilot, Gemini CLI. The repository carries everything the agent needs to do that well: `CLAUDE.md` orients it, and `docs/skills/` holds one "skill file" per subsystem with the patterns, the anti-patterns and the verification commands. What the agent *doesn't* know is what you want built, and whether you expect it to lean on the built-in features or reinvent them.

That is what a good prompt supplies. The prompts below are copy-ready for the tasks people start with. Each one names the layer to build on, the skill files to read first, and the gate that counts as done. Replace the parts in angle brackets.

## How a good SmallStack prompt is shaped

Every prompt below follows one shape, and it is worth knowing why:

1. **Say what you are building and for whom** — staff tool, end-user app, public site, API backend. SmallStack has different patterns for each, and the agent picks the wrong one if you don't say.
2. **Name the skill files to read first.** The agent will find them eventually, but naming them makes the first attempt the right one. `docs/skills/README.md` is the full index; `CLAUDE.md` has the "if the user wants X, read Y" table.
3. **Ask for the built-in seams by name** — a `CRUDView` with `enable_api` / `enable_mcp`, a `@dataset`, a `@scheduled` job, a status `Monitor`, a nav registration, a dashboard widget. An agent that doesn't know these exist will hand-roll a worse version.
4. **State the gate.** `make lint` (ruff, mypy, skill index) and `make test` must pass, and any new page gets a screenshot on two palettes. Saying so up front stops "done" from arriving before it is.
5. **Say what must stay generic.** If you're working in the upstream `smallstack/` repo, changes must stay reusable; in a downstream project, edit `apps/website/` and your own apps freely.

A prompt that does those five things gets code that integrates; a prompt that says "add a tickets page" gets a Django page that could have come from anywhere.

## Starting a project on SmallStack

**Build a new application on top of SmallStack**

> I'm building **<a help-desk tool for a small IT team>** on top of this SmallStack project. Before writing code, read `CLAUDE.md`, then `docs/skills/from-zero-to-running.md`, `docs/skills/django-apps.md`, `docs/skills/crud-views.md` and `docs/skills/modern-dark-theme.md`.
>
> Create a new app `apps/<tickets>/` with these models: **<Ticket (title, requester, assignee, priority, status, due_at), Comment>**. Give each a `CRUDView` with list/detail/create/edit/delete pages, `enable_api = True`, `enable_mcp = True` and `enable_search = True`, so the same declaration gives me the admin pages, a REST API, MCP tools for Claude and keyword search. Register the app in the sidebar nav and add a dashboard widget on `/smallstack/`. Use the theme's CSS variables only — no hard-coded colours — and follow the page patterns in the skill files rather than inventing a layout.
>
> Write tests under `apps/<tickets>/tests/`. Run `make lint` and `make test` until both pass, then screenshot the list page on the `purple` and `orange` palettes and show me. Don't commit; I'll review first.

**Turn the website pages into my product's site** (the public, non-admin part)

> I want the public site — the pages under `apps/website/` — to become **<the marketing site for Acme Scheduling: home, features, pricing, contact>**. Read `docs/skills/templates.md`, `docs/skills/navigation.md`, `docs/skills/modern-dark-theme.md` and `docs/skills/building-a-user-facing-site.md` first. Keep the SmallStack theme and base template; change content, structure and the topbar navigation. Branding comes from the `BRAND_*` settings and `static/brand/`, not from edits to the theme. Every page must look right on all six palettes in both light and dark mode; screenshot each new page on two palettes before telling me it's done.

**Build an end-user application** (signed-in customers, not staff)

> This is an app for **<our customers to track their own orders>**, not an admin tool. Read `docs/skills/building-a-user-facing-site.md` and `docs/skills/mcp/end-user-tools.md` before anything else — the tenancy rules there are the whole point. Use `LoginRequiredMixin`, scope every queryset by `request.user` in `get_list_queryset`, enforce writes in `check_object_permission` (not only `can_update`, which just decides which buttons render), and make the form scope its own foreign-key choices. Then build the `CRUDView`s for **<Order, Address>** with `enable_api` and `enable_mcp`, and prove in tests that one customer cannot read or write another's rows through the HTML pages, the REST routes or the MCP tools.

## Adding one capability

**Add a model with admin pages, REST and MCP in one go**

> Add a **<Vendor>** model to `apps/<inventory>/` with fields **<name, contact email, is_active, notes>**. Read `docs/skills/crud-views.md` and `docs/skills/mcp/enable-mcp-for-a-model.md`. One `CRUDView` class should give me the management pages, `/smallstack/api/...` REST routes and the MCP tools; add a migration, nav entry, tests, and run `make lint` and `make test`. Then run `python manage.py api_doctor` and `python manage.py mcp_doctor` and paste the results.

**Put something on the calendar**

> I want **<project milestones>** on the shared calendar at `/smallstack/calendar/`. Read `docs/skills/calendar.md` and `docs/skills/datasets.md`. If the dates live in a model column, declare a `@calendar_dataset` over it with `start`, `title`, `status` and the right `access`; if they're computed, write a `@calendar_provider`. Give the model's own list page a Table ⇄ Calendar ⇄ Board toggle with `CalendarDisplay` and `RangeBoardDisplay`. Add tests that the events appear in the right window and respect access.

**Make something report-able** (a dashboard builder, an export, an agent that queries data)

> Expose **<closed tickets>** as a `@dataset` so it can be filtered, charted and exported without more views. Read `docs/skills/datasets.md`. Declare the columns explicitly, mark the numeric ones that make sense as measures, add any ratio measure as a declared `measures=` entry (never an average of percentages), set `enable_api=True`, and check it in the staff browser at `/smallstack/datasets/browse/`.

**Run something on a schedule**

> I need **<a nightly digest email to each team lead>**. Read `docs/skills/scheduler.md` and `docs/skills/background-tasks.md`. Write it as a `@task` and declare the cadence with `@scheduled` so it appears in the scheduler UI with a run history, rather than as a cron script. Make it idempotent and safe to run twice. Show me how to run it once by hand and how to watch it on `/smallstack/scheduler/`.

**Gate an action behind a human decision**

> Before **<a refund over $500>** goes through, a manager has to approve it. Read `docs/skills/approvals.md` and `docs/skills/notifications.md`. Register an `@approval_kind`, file the request with `request_approval()` from the place the action starts, react to the decision in the kind's callback, and make sure the approvers get a bell notification. The action must not happen on a rejected or expired request; write that test first.

**Watch something's health on the status page**

> Add **<our payment provider's API>** to `/smallstack/status/`. Read `docs/skills/status-monitors.md`. Register a `Service` and a `Monitor` whose `check()` is cheap, decide whether it is public, and show me the public status page with it on. Don't add a new monitoring loop; the heartbeat already runs the registered monitors.

**Integrate with another system**

> When **<an order is created>**, **<Slack / Zapier / our ERP>** needs to hear about it; and **<Stripe>** needs to be able to call us back. Read `docs/skills/webhooks.md` first — it covers both directions. Use `enable_webhooks = True` on the `CRUDView` for the outbound side and shape the payload with `@webhook_transform`; use `@webhook_handler` with `@webhook_verifier` for the inbound side. Don't write an HTTP client or a signature check by hand; the framework has them.

**Publish writing**

> Set up a **<company changelog / engineering blog>** with an email list. Read `docs/skills/blog.md` and `docs/skills/rss.md`. Use the built-in blog app — a blog with the right visibility, the newsletter with double opt-in — rather than new models, and show me the public URL, the feed URL and where authors write.

**Build a page that fits the theme**

> Build **<a weekly review page for the support team>** under `apps/<support>/`. Before touching a template, read `docs/skills/modern-dark-theme.md` and `docs/skills/dashboard-cards.md`. Use `.card`, `.page-header-bleed`, `{% stat_card %}` and the theme's CSS variables; no hex colours, no `[data-theme="dark"]` overrides. When it renders, screenshot it on the `purple`, `orange` and `high-contrast` palettes and fix anything that goes brown or muddy before showing me.

## Operating a project

**Deploy**

> Deploy this project to **<a single VPS at example.com>** with Kamal. Read `docs/skills/kamal-deployment.md` and `docs/skills/docker-deployment.md`. Walk me through what you need from me (server, DNS, registry, secrets) before you change anything, then set it up, deploy, and confirm `/health/` and `/status/` answer.

**Pull in a new SmallStack release**

> This project is built on SmallStack and I want to update to the latest upstream release. Read `docs/skills/integration-workflow.md` and `docs/skills/downstream-release-migration.md`, then the `UPGRADING.md` and `CHANGELOG.md` entries between our version and the new one. Tell me what is breaking for *this* project before merging, merge, run migrations, `make lint` and `make test`, and summarise what changed in behaviour.

**Find out what's wrong**

> **<Claude Desktop can't see the MCP tools / Swagger is empty / the API returns 403>**. Read `docs/skills/cli-tools.md` first — there is a diagnostic command for most of this (`api_doctor`, `mcp_doctor`, `sc doctor all`). Run the right one, read `/smallstack/logs/` for the request, and explain the cause before proposing a fix.

## Things worth saying explicitly

- **"Don't hand-roll what exists."** Backups, OpenAPI validation, token minting, screenshots, health checks and search all have `manage.py` commands or framework seams. `docs/skills/cli-tools.md` is the lookup table; pointing the agent at it saves a reinvented wheel.
- **"Use the CSS variables."** The single most common agent mistake in this codebase is a hard-coded colour that looks fine on one palette and breaks on four others. Asking for a two-palette screenshot catches it every time.
- **"Scope by user."** For anything a non-staff user touches, say the words `get_list_queryset` and `check_object_permission`; the agent then builds tenancy in rather than bolting it on.
- **"Tests, lint, then show me."** `make lint` runs ruff, mypy and the skill-index check; `make test` is the suite. Asking for both before "done" is the difference between a demo and a merge.
- **"Keep it generic"** or **"this is downstream"** — tell the agent which repo it is in. The upstream framework must stay reusable; a project built on it can be as specific as it likes.

## Where the agent's knowledge lives

| File | What it gives the agent |
|---|---|
| `CLAUDE.md` | The orientation: what the project is, the read-first table, the conventions and anti-patterns |
| `docs/skills/README.md` | The full index of skill files, with "before X, read Y" guidance |
| `docs/skills/<topic>.md` | The patterns for one subsystem, including the bugs they prevent |
| `apps/smallstack/docs/` | These help pages — the human-facing reference the agent can also read |
| `/api/schema/openapi.json`, `mcp_doctor` | The live surface of your own project once it's running |

If a prompt you need isn't here, the pattern still holds: say the goal, name the skill, ask for the seam, state the gate.
