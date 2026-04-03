# Skill: Update Docs & Skills Post Changes

When the user says "update docs and skills" (or similar), this skill defines which files to check and update based on what area of SmallStack was changed. The goal: keep documentation accurate and complete after code changes, without missing files or duplicating content.

## How It Works

1. **Identify the change area** — What part of SmallStack was modified? (API, auth, theming, etc.)
2. **Look up the file groups below** — Each area lists the docs and skills that reference it
3. **Read each file** — Check if the change is already documented or needs to be added
4. **Update or create** — Weave changes into existing docs where they fit. Create new docs only when a feature is genuinely new and doesn't belong in an existing page.

## File Groups by Change Area

### API System (`apps/smallstack/api.py`, `apps/smallstack/openapi.py`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/api.md` | Full API reference: auth, CRUD, endpoints, config, serialization |
| Skill | `docs/skills/api-discovery.md` | Schema endpoints, OpenAPI, OPTIONS metadata, Swagger/ReDoc |
| Skill | `docs/skills/custom-api-endpoints.md` | `@api_view` decorator, non-CRUD endpoints |
| Help | `apps/help/content/developers/custom-api-endpoints.md` | User-facing custom endpoint guide |
| Help | `apps/smallstack/docs/explorer-rest-api.md` | Explorer API (uses same auth/serialization layer) |
| Config | `apps/smallstack/docs/_config.yaml` | Help page registry (add new pages here) |

### Authentication & Tokens (`apps/smallstack/models.py` APIToken, `apps/smallstack/api.py` auth views)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/api.md` | Token types, access levels, auth endpoints |
| Skill | `docs/skills/authentication.md` | User model, auth views, login/signup |
| Help | `apps/smallstack/docs/authentication.md` | User-facing auth docs |

### Activity Tracking & Observability (`apps/activity/`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/activity-tracking.md` | RequestLog model, middleware, config |
| Skill | `docs/skills/logging-audit.md` | Logging config, audit trail, LogEntry |
| Help | `apps/smallstack/docs/activity-tracking.md` | User-facing activity tracking guide |
| Help | `apps/smallstack/docs/logging-audit.md` | User-facing logging/audit guide |

### Middleware (`apps/smallstack/middleware.py`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/activity-tracking.md` | ActivityMiddleware docs |
| Skill | `docs/skills/settings.md` | MIDDLEWARE list reference |
| Skill | `docs/skills/timezones.md` | TimezoneMiddleware |

### Navigation & Sidebar (`apps/smallstack/navigation.py`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/navigation.md` | Nav registry, zones, sidebar/topbar |
| Help | `apps/help/content/components/navigation.md` | User-facing nav docs |
| Help | `apps/smallstack/docs/navigation.md` | Bundled nav reference |

### Templates & Theming (`templates/`, `static/`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/templates.md` | Template inheritance, blocks, includes |
| Skill | `docs/skills/theming-system.md` | CSS vars, palettes, dark mode |
| Skill | `docs/skills/building-themed-pages.md` | Building pages that fit the theme |
| Skill | `docs/skills/admin-page-styling.md` | Definitive UI component reference |
| Skill | `docs/skills/components.md` | UI component catalog |

### CRUDView (`apps/smallstack/crud.py`, `apps/smallstack/views.py`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/crud-views.md` | CRUDView class, actions, config |
| Skill | `docs/skills/django-apps.md` | Creating apps with CRUDView |
| Skill | `docs/skills/api.md` | API integration via enable_api |
| Help | `apps/smallstack/docs/building-crud-pages.md` | User-facing CRUD guide |

### Explorer (`apps/smallstack/explorer.py`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/explorer.md` | Explorer overview |
| Help | `apps/smallstack/docs/explorer.md` | User-facing explorer guide |
| Help | `apps/smallstack/docs/explorer-admin-api.md` | ModelAdmin attribute reference |
| Help | `apps/smallstack/docs/explorer-rest-api.md` | Explorer REST API |
| Help | `apps/smallstack/docs/explorer-composability.md` | Embedding explorer |

### Settings & Configuration (`config/settings/`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/settings.md` | All settings, env vars, feature flags |
| Help | `apps/smallstack/docs/settings-configuration.md` | User-facing settings guide |

### Background Tasks (`apps/tasks/`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/background-tasks.md` | Task system, worker, queues |
| Help | `apps/smallstack/docs/background-tasks.md` | User-facing tasks guide |

### Deployment (Docker, Kamal)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/docker-deployment.md` | Docker setup |
| Skill | `docs/skills/kamal-deployment.md` | Kamal deployment |
| Help | `apps/smallstack/docs/docker-deployment.md` | User-facing Docker guide |
| Help | `apps/smallstack/docs/kamal-deployment.md` | User-facing Kamal guide |

### Help System (`apps/help/`)

| Type | File | What it covers |
|------|------|----------------|
| Skill | `docs/skills/help-documentation.md` | Help system architecture, creating pages |
| Help | `apps/smallstack/docs/help-system.md` | User-facing help system guide |

## Cross-Cutting Updates

Some changes affect multiple groups. Always check:

- **`docs/skills/README.md`** — If you add a new skill file, add it to the table and usage list
- **`apps/smallstack/docs/_config.yaml`** — If you add a new help page, register it here
- **`CLAUDE.md`** (workspace root) — If architecture changes significantly

## Decision: Update Existing vs Create New

- **Update existing** when: the change extends or modifies a feature already documented
- **Create new** when: the feature is genuinely new, has its own URL/config surface, and would make an existing doc too long or unfocused
- **Both** when: a new feature needs its own page AND existing pages need cross-references to it

## Checklist Template

When updating docs after a change:

```
Change area: [e.g., API System]
Files modified: [list code files changed]

Skills to check:
- [ ] docs/skills/api.md
- [ ] docs/skills/api-discovery.md
- [ ] ...

Help docs to check:
- [ ] apps/smallstack/docs/...
- [ ] apps/help/content/...

Config to check:
- [ ] apps/smallstack/docs/_config.yaml (new pages)
- [ ] docs/skills/README.md (new skills)

Actions taken:
- [ ] Updated [file] — added [what]
- [ ] Created [file] — new page for [what]
```
