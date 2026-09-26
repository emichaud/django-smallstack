---
title: README
description: Project overview and quick start guide
---

# Django SmallStack

*One small backend. Many roles.*

A modern, batteries-included Django foundation that plays many roles in your stack — an admin app, a REST backend for your React/Svelte/Solid frontend, an MCP server, a search engine, an integration hub, and a task runner — all from a single model definition. Production-ready with SQLite, Docker, and zero-downtime Kamal deployment. Clone it, customize it, ship it.

SmallStack is not a theme you have to implement — it's a production-ready system with clear patterns for you to extend with your own ideas and creativity. You focus on what makes your app unique, and SmallStack handles the platform.

📖 **Full docs & the full story → [www.smallstack.site](https://www.smallstack.site/)**

## Features

### Five surfaces from one model
Declare a `CRUDView` and opt in with flags — `enable_api`, `enable_mcp`, `enable_search`. One model becomes an HTML admin, a REST API (with OpenAPI), MCP tools for AI agents, a full-text search interface, and a terminal CLI (`sc`). Change the model once; all five stay in sync.

### REST API & bundled clients
Bearer-token REST with an OpenAPI 3.0 spec, Swagger UI, and ReDoc — plus typed TypeScript/JS and Python clients (`clients/`) so a React, Svelte, Solid, or Streamlit frontend can talk to it immediately.

### MCP server
A first-class Model Context Protocol server (OAuth + JSON-RPC) exposes your models as tools for Claude Desktop and agent frameworks — no extra setup.

### Full-text search
Real ranked search — SQLite FTS5 or Postgres SearchVector — with a Ctrl-K omnibar, a search page, an MCP retrieval tool (RAG), and custom variants via SearchBuilder.

### Webhooks & feeds
Signed outbound webhooks on model change and verified inbound receivers (seams for Zapier/n8n/Stripe/Slack), plus RSS/Atom feeds you can publish from any model or consume on a schedule.

### Background tasks & scheduler
Django's Tasks framework is pre-configured with a database backend, plus a `@scheduled` recurring-job scheduler with a themed UI. Send emails, process data, and run jobs — no Redis or Celery to operate.

### Approvals & notifications
A generic human-in-the-loop gate: apps (or AI agents, via MCP) file an approval request, a person decides in a themed console, and your code reacts via callback, signal, webhook, or polling. Decisions and requests fan out to an in-app notification bell + inbox and branded email.

### Profile & authentication
Complete user profile management (photo, cover image, bio, location, display name) on a custom User model with email login, password reset flows, and secure sessions.

### Help system
Built-in documentation with markdown support, table of contents, search, and easy-to-edit content files. Perfect for user guides or product docs.

### Theming
Beautiful light and dark modes with six color palettes and CSS custom properties. Customize colors, shadows, and spacing from a single file. User preferences are saved.

### Docker & SQLite
Production-ready Docker (multi-service compose, health checks, background worker) with SQLite stored outside the container — reliable data storage that backs up with your VPS, no database service fees. [Upgrade to PostgreSQL](/help/smallstack/database-postgresql/) when you need it.

## Built on Django Best Practices

- **Split settings** - Separate configurations for development, production, and testing
- **Apps in dedicated folder** - Clean organization with all apps in `apps/` directory
- **Custom User model** - Extensible user model from day one
- **Signals in separate files** - Clean separation of concerns
- **Tests alongside apps** - Tests live with their apps for easy maintenance
- **URL namespacing** - Organized URL patterns (e.g., `help:index`)
- **Organized static files** - Structured CSS and JavaScript
- **Template structure mirrors apps** - Intuitive template organization
- **SQLite with data separation** - Database stored in `/data/` directory, persists across container rebuilds

## Quick Start

### Prerequisites

- Python 3.12+
- [UV](https://github.com/astral-sh/uv) package manager (recommended)
- Docker Desktop (for containerized deployment)

### Local Development

1. **Clone and enter the project:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/django-smallstack.git
   cd django-smallstack
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

4. **Run migrations:**
   ```bash
   uv run python manage.py migrate
   ```

5. **Create a superuser:**
   ```bash
   uv run python manage.py create_dev_superuser
   ```

6. **Start the development server:**
   ```bash
   uv run python manage.py runserver
   ```

7. **Open your browser:**
   - Homepage: http://localhost:8000
   - Admin: http://localhost:8000/admin

### Docker Deployment

1. **Build and run:**
   ```bash
   docker compose up -d
   ```

2. **Access the application:**
   - Homepage: http://localhost:8010

## Project Structure

```
django-smallstack/
├── apps/                      # Django applications
│   ├── accounts/              # Custom user model & auth
│   ├── smallstack/           # Theme helpers (pure presentation)
│   ├── profile/               # User profile management
│   ├── help/                  # Documentation system
│   └── tasks/                 # Background tasks
├── config/                    # Project configuration
│   └── settings/              # Split settings
│       ├── base.py            # Shared settings
│       ├── development.py     # Dev-specific settings
│       ├── production.py      # Production settings
│       └── test.py            # Test settings
├── templates/                 # HTML templates
│   ├── smallstack/           # Base templates & includes
│   ├── profile/               # Profile templates
│   ├── help/                  # Help system templates
│   └── registration/          # Auth templates
├── static/                    # Static files (CSS, JS)
├── docs/                      # Additional documentation
│   └── skills/                # AI assistant skill files
├── docker-compose.yml         # Docker composition
├── Dockerfile                 # Container definition
└── pyproject.toml             # Dependencies & tools config
```

## Built to Extend

{{ project_name }} comes pre-populated with working examples and sensible defaults. Use it as-is, or customize everything to build your vision.

- **Split settings for dev/prod** - Environment-specific configuration
- **UV package management** - Fast, modern Python packaging
- **Admin theme helpers** - Template tags for breadcrumbs, navigation
- **AI skill files included** - Documentation for AI assistants
- **Starter template page** - Copy-paste template for new pages at `/starter/`

## Development

### Running Tests

```bash
uv run pytest
```

### Code Quality

```bash
# Lint and fix
uv run ruff check --fix .

# Format
uv run ruff format .
```

### Background Worker

For development with background tasks:

```bash
uv run python manage.py db_worker
```

## Documentation

Once running, visit `/help/` for comprehensive documentation including:

- Getting Started guide
- Theming customization
- Docker deployment
- Background tasks
- Adding new pages
