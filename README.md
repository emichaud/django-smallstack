# Django SmallStack

*Django that doesn't get in your way. Focus on your idea, not the stack.*

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![Django 6.1](https://img.shields.io/badge/django-6.1-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)

**A platform to build apps on.** The admin shell, auth, CRUD pages, REST, MCP, search, webhooks,
feeds, a scheduler, approvals, notifications, dashboards and publishing are already built, tested
and themed, so your project starts at the business logic. SQLite by default, no external services.

- **What it is and what you get:** [docs/smallstack.md](docs/smallstack.md)
- **Writing code by hand:** [Plain Django on SmallStack](apps/smallstack/docs/plain-django.md): a view, a form, a template and a test, with nothing SmallStack-specific to learn first
- **Full docs and guides:** [www.smallstack.site](https://www.smallstack.site/), and `/smallstack/help/` once it's running
- **What changed:** [CHANGELOG.md](CHANGELOG.md) · moving a project onto a new release: [UPGRADING.md](UPGRADING.md)
- **Working with an AI agent:** [AGENTS.md](AGENTS.md) and the skills in [docs/skills/](docs/skills/README.md)

## Quick start

**Prerequisites:** [uv](https://docs.astral.sh/uv/) (it manages Python for you) and `make`.

```bash
git clone https://github.com/emichaud/django-smallstack.git myapp
cd myapp
make setup    # uv sync + migrate + create dev superuser (admin/admin)
make run      # dev server on port 8005
```

Open http://localhost:8005 and log in with `admin` / `admin`.
**Docker:** `cp .env.example .env && docker compose up -d` (port 8010).

## Building your project on SmallStack

This file is yours to rewrite: SmallStack keeps its own description in `docs/smallstack.md`.
Your pages go in `apps/website/` and apps of your own. SmallStack's demo pages are
`apps/showcase/`, which you can delete. Pulling a new release is
[docs/skills/integration-workflow.md](docs/skills/integration-workflow.md).

## License

MIT — use it, modify it, ship it.
