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
| [django-apps.md](django-apps.md) | Creating apps, CRUDView + tables2 management pages, title bar pattern |
| [templates.md](templates.md) | Template inheritance, blocks, includes, common patterns |
| [admin-page-styling.md](admin-page-styling.md) | **Definitive UI reference**: buttons, cards, tables, stat cards, action cards, tabs, filter toggles, forms, modals, starter template |
| [theming-system.md](theming-system.md) | CSS variables, palettes, dark mode |
| [building-themed-pages.md](building-themed-pages.md) | Recipe guide: color-mix scale, building pages that fit all modes and palettes |
| [adding-your-own-theme.md](adding-your-own-theme.md) | Adding a custom CSS framework alongside SmallStack's built-in theme |
| [theme-scenarios.md](theme-scenarios.md) | Three theme integration scenarios: public-only, user login, or build on SmallStack |
| [authentication.md](authentication.md) | Custom user model, auth views, protecting views |
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
| [api-discovery.md](api-discovery.md) | API discovery endpoints: schema introspection, OpenAPI spec, OPTIONS metadata |
| [custom-api-endpoints.md](custom-api-endpoints.md) | Building non-CRUD API endpoints with the `@api_view` decorator |
| [dashboard-widgets.md](dashboard-widgets.md) | Dashboard widget protocol: `DashboardWidget` class, Explorer vs standalone registration, data layer, REST API |
| [update-docs-and-skills.md](update-docs-and-skills.md) | File group map for updating docs/skills after code changes |

## Usage

AI agents should read relevant skill files before making changes to the corresponding parts of the codebase. For example:

- Before creating a new app → read `django-apps.md`
- Before creating templates → read `templates.md`
- Before building any admin/management page → read `admin-page-styling.md` (buttons, cards, tables, forms, etc.)
- Before modifying CSS/theming → read `theming-system.md`
- Before building a new page that should fit the SmallStack theme → read `building-themed-pages.md`
- Before adding a custom theme (Bootstrap, Tailwind, etc.) → read `adding-your-own-theme.md`
- Before deciding which theme approach to take → read `theme-scenarios.md`
- Before working with auth → read `authentication.md`
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
- Before integrating with the SmallStack API → read `api-discovery.md`
- Before building custom (non-CRUD) API endpoints → read `custom-api-endpoints.md`
- Before adding dashboard widgets → read `dashboard-widgets.md`
- Before updating docs after code changes → read `update-docs-and-skills.md`

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
