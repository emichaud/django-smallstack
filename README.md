# Django SmallStack

*A stable foundation for your next small Django app.*

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![Django 6.0](https://img.shields.io/badge/django-6.0-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)

> **Note:** SmallStack is pre-1.0 and changing rapidly. The API and conventions will stabilize at the 1.0.0 milestone.

SmallStack is a batteries-included Django starter for small teams, self-hosters, and container deployments. Clone it, customize it, ship it.

**SQLite is a first-class citizen.** SmallStack comes configured to run production-ready on SQLite — no database service fees, just simple reliable storage that backs up with your VPS. Need Postgres? The [docs](https://django-small-stack.space/) include setup instructions.

**Build websites, API servers, or background task runners.** SmallStack includes built-in support for scheduled background tasks via Django 6's Tasks framework — no Redis or Celery required.

![Django SmallStack Homepage](apps/help/smallstack/images/smallstack-home.png)

## Theming

SmallStack extends Django's built-in admin theme — forms, widgets, tables, and all the standard elements — without any external CSS. It adds dark/light mode support with multiple color palettes, all driven by CSS custom properties.

**Bring your own theme.** SmallStack separates public pages from management pages. Use your own CSS framework for your app while SmallStack preserves its own theme for the included tools: Explorer, Activity, Backups, Status, Users, and Dashboard. Build your app your way, then log in to manage it with the built-in SmallStack tools when you need to.

<p>
  <img src="apps/help/smallstack/images/smallstack-docs.png" alt="Help System Dark Mode" width="49%">
  <img src="apps/help/smallstack/images/smallstack-docs-light.png" alt="Help System Light Mode" width="49%">
</p>

## What's Included

- **Authentication** — custom User model, login, signup, password reset
- **User profiles** — photo, bio, timezone, display name
- **Model Explorer** — auto-generated CRUD views for any registered model
- **Activity tracking** — request logging with staff dashboard and auto-pruning
- **Database backups** — on-demand + scheduled, with retention policies
- **Background tasks** — database-backed task queue, no external services
- **Help system** — markdown docs with search and table of contents
- **htmx** — partial page updates with no build step, vendored locally
- **Docker + Kamal** — production-ready container config with zero-downtime deploys

## Quick Start

### Prerequisites

- Python 3.12+
- [UV](https://github.com/astral-sh/uv) package manager

### Setup

```bash
git clone https://github.com/emichaud/django-smallstack.git myapp
cd myapp
make setup    # install deps, migrate, create dev superuser (admin/admin)
make run      # start dev server
```

Open http://localhost:8005 and log in with `admin` / `admin`.

### Docker

```bash
docker compose up -d
```

Access at http://localhost:8010.

## Project Structure

```
django-smallstack/
├── apps/                      # Django applications
│   ├── accounts/              # Custom user model & auth
│   ├── smallstack/            # Theme, CRUD library, admin tools
│   ├── profile/               # User profile management
│   ├── help/                  # Documentation system
│   ├── activity/              # Request tracking & dashboard
│   ├── explorer/              # Auto-generated model CRUD
│   └── tasks/                 # Background tasks
├── config/
│   └── settings/              # Split settings (base, dev, prod, test)
├── templates/                 # HTML templates
├── static/                    # CSS, JS, brand assets
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Development

```bash
make test         # run pytest with coverage
make lint         # ruff check
make lint-fix     # ruff check --fix
```

Once running, visit `/help/` for full documentation including getting started, theming, deployment, and more.

## Learn More

**[django-small-stack.space](https://django-small-stack.space/)**

## License

MIT — use it, modify it, ship it.
