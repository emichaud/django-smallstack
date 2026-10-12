# Welcome

You made it — nice. This is your project's documentation home, and everything you need is right here.

SmallStack is a Django platform to build applications on. The admin shell, authentication, CRUD pages, REST, MCP, search, webhooks, feeds, a scheduler, approvals, notifications and publishing are already built, tested and themed — so your project starts at the business logic. You write the models; every platform surface picks them up.

## Where to start

**Brand new?** Start with the setup guide — it walks you through the first things to configure after cloning:

- [Getting Started](/smallstack/help/getting-started/) — First-run setup, branding, creating pages, and deployment basics
- [Quick Setup (TL;DR)](/smallstack/help/quick-setup/) — Clone to deploy in 8 steps
- [Your first MCP app in 10 minutes](/smallstack/help/smallstack/mcp-first-app/) — model → CRUDView → REST → MCP tools → Claude Desktop

**Ready to build?** Jump into the reference docs:

- [SmallStack Reference](/smallstack/help/smallstack/) — Every feature, component, and configuration option
- [Building CRUD pages](/smallstack/help/smallstack/building-crud-pages/) — One declaration → HTML, REST, MCP, search, webhooks, feeds and CLI

## What's included

Everything below works out of the box, is themed for all six palettes in light and dark, and is a single setting away from off.

| Feature | What it does |
|---------|--------------|
| **Authentication** | Login, signup, password reset — themed and ready; custom User model |
| **User profiles** | Photo, bio, timezone, color palette preference |
| **Theming** | 6 palettes × light/dark, user-selectable; semantic CSS variables so your pages inherit it |
| **CRUDView** | Model → admin pages, REST + OpenAPI, MCP tools, search, webhooks, feeds — [reference](/smallstack/help/smallstack/building-crud-pages/) |
| **Model Explorer** | Browse and edit every registered model at `/smallstack/explorer/` |
| **REST API** | Bearer-token auth, Swagger UI + ReDoc, typed TypeScript and Python clients — [docs](/smallstack/help/smallstack/api-documentation/) |
| **MCP server** | OAuth 2.0 + PKCE JSON-RPC server for Claude Desktop and agent frameworks — [docs](/smallstack/help/smallstack/mcp/) |
| **Search** | FTS5 / Postgres ranked search, Ctrl-K omnibar, `search_all` MCP tool — [docs](/smallstack/help/smallstack/search/) |
| **Webhooks** | Signed outbound delivery on model change, verified inbound receivers, replay — [docs](/smallstack/help/smallstack/webhooks/) |
| **Feeds** | RSS/Atom for any model with one flag, or a curated feed; consume external feeds — [docs](/smallstack/help/smallstack/feeds/) |
| **Background tasks & scheduler** | DB-backed task queue plus recurring `@scheduled` jobs with a themed UI — [docs](/smallstack/help/smallstack/scheduler/) |
| **Approvals** | Human-in-the-loop gate: apps or AI agents file a request, a person decides, your code reacts — [docs](/smallstack/help/smallstack/approvals/) |
| **Notifications** | `notify()` with a topbar bell, unread badge and inbox — [docs](/smallstack/help/smallstack/notifications/) |
| **Runbook** | Versioned markdown documents with a split editor, slide and step views — [docs](/smallstack/help/runbook/getting-started/) |
| **Blog & newsletter** | Per-user blogs, a writing studio, runbook publishing, public feeds and a durable newsletter sender — [docs](/smallstack/help/blog/) |
| **Datasets** | Expose a filtered queryset as typed rows and columns for dashboards and charts |
| **Activity & logs** | Request logging with a staff dashboard; DB-backed log capture at `/smallstack/logs/` — [docs](/smallstack/help/smallstack/logging-audit/) |
| **Status monitoring** | Uptime checks, a public status page, pluggable per-app monitors — [docs](/smallstack/help/smallstack/uptime-monitoring/) |
| **Database backups** | On-demand + scheduled SQLite snapshots, download or restore |
| **Help system** | Markdown docs with search — you're reading it now |

## Build on the same seams

The built-in apps aren't special-cased. Your app registers through the same hooks — `nav.register()` for navigation, `dashboard.register()` for a widget on `/smallstack/`, a Service + Monitor pair for the status page, `@scheduled` for recurring work, `@approval_kind` for a human gate, `notify()` for in-app notifications, `@webhook_handler` for inbound events, `@dataset` for chart-ready rows, and `help_content_dir` for docs like these. See [Extending with AI](/smallstack/help/smallstack/extending-with-ai/) for how the `docs/skills/` files brief an AI agent on each of them.

## Adding your own docs

This help system is yours to extend. Add project-specific documentation right alongside the SmallStack reference:

1. Create a `.md` file in `apps/help/content/`
2. Add it to `apps/help/content/_config.yaml` under your section's pages
3. It appears at `/smallstack/help/your-page-slug/`

Apps can ship their own docs too: set `help_content_dir` and `help_section_slug` on the AppConfig and the pages appear as a section (the blog and runbook sections work this way). See [Using the Help System](/smallstack/help/smallstack/help-system/) for the full guide.

## Quick links

- [Starter Page](/starter/) — See all UI components in action
- [Layout Gallery](/smallstack/layouts/) — Preview sidebar + topbar combinations
- [Theming Guide](/smallstack/help/smallstack/theming/) — Colors, dark mode, custom palettes
- [CLI reference](/smallstack/help/smallstack/cli-reference/) — Every `manage.py` command, Make target and the `sc` CLI
- [FAQ](/smallstack/help/smallstack/faq/) — Common questions answered
