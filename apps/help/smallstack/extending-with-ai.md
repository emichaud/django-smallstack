---
title: Extending with AI
description: Using AI assistants to accelerate development
---

# Extending with AI

{{ project_name }} was jointly developed with the help of **Claude**, an AI assistant by Anthropic. The project includes structured "skill files" in `docs/skills/` that teach AI agents how the codebase works — its patterns, conventions, and the right way to add features. When you ask an AI to build something, it reads the relevant skill and produces code that fits naturally into the existing project.

## AI Skills Reference

Skills are markdown files in `docs/skills/`. An AI agent reads the relevant skill before making changes to that part of the codebase.

### Core Development

| Skill | File | What It Teaches |
|-------|------|-----------------|
| **Django Apps & CRUD** | `django-apps.md` | Creating new apps, CRUDView + django-tables2 management pages, title bar pattern, search, stat cards, modal drilldowns |
| **Templates** | `templates.md` | Template inheritance, blocks, includes, common layout patterns |
| **Theming** | `theming-system.md` | CSS variables, palettes, dark/light mode, UI component styling |
| **Authentication** | `authentication.md` | Custom user model, auth views, protecting views with mixins |
| **HTMX Patterns** | `htmx-patterns.md` | HTMX setup, CSRF handling, partial responses, dual-response views, OOB swaps |
| **Settings** | `settings.md` | Split settings, environment variables, feature flags, BRAND_* config |
| **Timezones** | `timezones.md` | Timezone middleware, per-user timezone, localtime_tooltip tag |

### Infrastructure

| Skill | File | What It Teaches |
|-------|------|-----------------|
| **Background Tasks** | `background-tasks.md` | Django Tasks framework with django-tasks-db backend |
| **Activity Tracking** | `activity-tracking.md` | HTTP request logging middleware, dashboard, pruning configuration |
| **Logging & Audit** | `logging-audit.md` | Django logging configuration and audit trail |
| **Help System** | `help-documentation.md` | Adding help pages, sections, bundled SmallStack docs |
| **Screenshots** | `screenshot-workflow.md` | Visual verification with shot-scraper and screenshot_auth |

### Deployment & Workflow

| Skill | File | What It Teaches |
|-------|------|-----------------|
| **Docker** | `docker-deployment.md` | Docker Compose setup, services, volumes, local development |
| **Kamal** | `kamal-deployment.md` | Zero-downtime VPS deployment, SSL, server configuration |
| **Development Workflow** | `development-workflow.md` | Branching, testing, coverage, commit style |
| **Release Process** | `release-process.md` | Versioning, release checklist, GitHub releases |
| **Integration** | `integration-workflow.md` | Pulling upstream changes into downstream projects, deploying |

## The CRUD Management Page Pattern

The most common task when extending {{ project_name }} is adding a management page for a new model. The `django-apps.md` skill teaches the complete pattern, which is summarized here.

### Page Anatomy

Every management list page follows this consistent structure:

**Title Bar** — colored header with title, breadcrumbs on the left, and summary number cards or action buttons on the right.

**Stat Cards** (optional) — clickable dashboard counters below the title bar. Clicking one opens a modal drilldown with detail rows.

**Search Bar** (optional) — HTMX-powered search that filters the table progressively without page reload.

**Sortable Table** — django-tables2 table with themed styling, column sorting, and pagination. Click column headers to sort.

**Stat Modal** — an 80%-width popup that appears when clicking stat cards, showing a detail table inside.

### What CRUDView Generates

A single Python class produces all the views and URL patterns:

```python
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

class WidgetCRUDView(CRUDView):
    model = Widget
    url_base = "manage/widgets"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    table_class = WidgetTable
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
```

This generates four URL patterns:

| URL | Purpose |
|-----|---------|
| `/manage/widgets/` | Searchable list with sortable table |
| `/manage/widgets/new/` | Create form |
| `/manage/widgets/<pk>/edit/` | Update form |
| `/manage/widgets/<pk>/delete/` | Delete confirmation |

### Reusable Table Columns

The `apps.smallstack.tables` module provides themed column types that integrate with CRUDView:

| Column | Purpose |
|--------|---------|
| `DetailLinkColumn` | Wraps cell value in a link to the detail or edit page |
| `BooleanColumn` | Renders True/False as a themed checkmark or dash |
| `ActionsColumn` | Edit and Delete icon buttons |

```python
from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn

class WidgetTable(tables.Table):
    name = DetailLinkColumn(url_base="manage/widgets", link_view="update")
    is_active = BooleanColumn()
    actions = ActionsColumn(url_base="manage/widgets")

    class Meta:
        model = Widget
        attrs = {"class": "crud-table"}   # Required for theme styling
```

### The Title Bar Convention

All management pages use the same title bar layout:

- **Left:** Page title (h1), optional subtitle, inline breadcrumbs (Home / Section / Page)
- **Right:** Summary number cards, action buttons, or links
- **Breadcrumbs block:** Emptied (`{% block breadcrumbs %}{% endblock %}`) since breadcrumbs are inline in the title bar

Number cards in the title bar use this pattern:

```html
<div style="text-align: center; padding: 8px 16px;
     background: color-mix(in srgb, var(--primary) 10%, var(--body-bg));
     border-radius: var(--radius-sm, 6px);">
    <div style="font-size: 1.5rem; font-weight: 700;
         color: var(--primary);">{{ count }}</div>
    <div style="font-size: 0.7rem; color: var(--body-quiet-color);
         text-transform: uppercase;">Label</div>
</div>
```

This convention is used consistently across User Manager, Activity Requests, Activity Users, Backups, Backup Detail, and Timezone Dashboard pages.

## Reference Implementations

These existing pages demonstrate the full pattern:

| Page | URL | Features |
|------|-----|----------|
| **User Manager** | `/manage/users/` | CRUDView + tables2 + search + stat cards + modal drilldowns |
| **Timezone Dashboard** | `/manage/users/timezones/` | Standalone tables2 + search + title bar number cards |
| **Activity Requests** | `/activity/requests/` | HTMX tabbed views, tables2 for Recent/Top Paths tabs |
| **Activity Users** | `/activity/users/` | HTMX tabs, title bar number cards |
| **Backups** | `/backups/` | Title bar with action cards, stat cards, modal drilldowns |
| **Backup Detail** | `/backups/<pk>/` | Title bar with status/size cards, timeline, detail table |

The **User Manager** (`apps/usermanager/`) is the canonical reference — it demonstrates every pattern including CRUDView with search, custom table columns, stat card drilldowns, HTMX partial responses, profile form integration, and the title bar convention.

## How to Use with an AI Assistant

### Adding a New Model with Management Pages

> "Add a Widget model to a new myfeature app with fields name, category, is_active, and owner. Create CRUD management pages following the SmallStack pattern."

The AI reads `docs/skills/django-apps.md` and produces the complete app: model, table, CRUDView, templates, URLs, sidebar link, settings registration, migrations, and tests.

### Adding Search to an Existing Page

> "Add HTMX search to the widget list page so users can filter by name or category without page reload."

The AI knows to override `_make_view`, add queryset filtering, return the table partial for HX-Request headers, and include the reusable search bar template.

### Adding Stat Cards with Drilldowns

> "Add dashboard stat cards showing total, active, and inactive widget counts to the widget list page, with modal drilldowns that list the items."

The AI wires up the stat-card-clickable HTML, HTMX endpoint, backend view returning an HTML table fragment, and includes the stat modal template.

### Converting Old Tables to tables2

> "Convert the errors tab on the activity requests page from hand-written HTML to django-tables2 with column sorting."

The AI creates a Table class, updates the view to use RequestConfig, and replaces the template HTML with `{% render_table table %}`.

## CLAUDE.md Integration

The project includes a `CLAUDE.md` file in the workspace root that provides top-level guidance to AI assistants. It covers:

- Project directory structure and which project is which
- The fix-upstream pattern (fix in base, pull to downstream)
- Common commands (`make setup`, `make run`, `make test`)
- Architecture overview (apps, settings, templates, theming)
- Key conventions (user model, mixins, URL namespaces)
- Links to skill files for deeper reference

When an AI assistant opens the project, `CLAUDE.md` is loaded automatically. The skill files in `docs/skills/` provide deeper reference for specific tasks.

## Adding New Skills

When you add a significant new system, create a corresponding skill file in `docs/skills/`:

1. **Overview** — what the feature does and why
2. **File locations** — where the code lives
3. **Step-by-step guide** — how to use or extend it
4. **Configuration** — settings and options
5. **Code examples** — concrete snippets an AI can follow
6. **Best practices** — what to do and what to avoid

Then update `docs/skills/README.md` to include it in the skills table.
