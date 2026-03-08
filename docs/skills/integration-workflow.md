# Skill: Integration Workflow

How to pull SmallStack upstream changes into downstream projects and deploy.

## Overview

SmallStack is an upstream package. Downstream projects clone it and add their own business logic. This workflow covers pulling updates, resolving conflicts, and redeploying.

## Downstream Projects

| Project | Directory | Deployment | Purpose |
|---------|-----------|------------|---------|
| smallstack_web | `../smallstack_web/` | django-small-stack.space | Marketing/demo site |
| opshugger | `../opshugger/` | www.opshugger.com | IT operations tool |

## Pull Upstream Updates

### First-Time Setup

If the downstream project doesn't have an upstream remote:

```bash
cd ../smallstack_web
git remote add upstream https://github.com/emichaud/django-smallstack.git
git fetch upstream
```

### Regular Pull

```bash
cd ../smallstack_web
git fetch upstream
git merge upstream/main
```

### Handling Merge Conflicts

Common conflict areas and resolution strategies:

| File | Strategy |
|------|----------|
| `uv.lock` | Take upstream version (`git checkout --theirs uv.lock`), then `uv sync --all-extras` |
| `pyproject.toml` | Keep downstream deps, take upstream version bump |
| `config/settings/base.py` | Merge carefully — downstream may have custom settings |
| `templates/smallstack/` | Take upstream changes (downstream should use `templates/website/`) |
| `static/smallstack/` | Take upstream changes (downstream should use `static/css/`, `static/js/`) |
| `apps/smallstack/` | Take upstream — this is core SmallStack code |
| `apps/profile/models.py` | Merge — may have custom palette choices |
| `Makefile` | Merge — downstream may have custom targets |
| `.env` / `.env.example` | Merge — add new upstream vars, keep downstream values |

### Post-Merge Steps

```bash
# Install any new dependencies
uv sync --all-extras

# Run migrations (upstream may have added new ones)
make migrate

# Run tests
make test

# Verify lint
make lint

# Start dev server and spot-check
make run
```

## Deploying Downstream

### Kamal Deployment (opshugger, smallstack_web)

```bash
git add -A
git commit -m "chore: Pull upstream SmallStack vX.Y.Z"
git push origin main
kamal deploy
```

Verify after deploy:
```bash
kamal app logs                      # Check for startup errors
```

### Docker Deployment

```bash
git push origin main
docker compose up -d --build
```

## Issue Tracking

When pulling upstream reveals issues in a downstream project, determine the root cause:

1. **Upstream bug** — fix in `smallstack/`, push, re-pull downstream
2. **Downstream-specific issue** — fix in the downstream project
3. **Documentation gap** — update `docs/skills/` or `apps/help/smallstack/` in upstream

### Suggesting Upstream Improvements

When working in downstream projects, note patterns that could improve upstream:

- Missing documentation that slowed you down
- Configuration that should have a better default
- Features that every downstream project needs
- Merge conflicts that could be avoided with better file organization

File issues or make the fix directly in `smallstack/` following the fix-upstream pattern.

## Pre-Integration Checklist

Before pulling upstream into a production downstream project:

- [ ] Read the upstream release notes (`gh release view vX.Y.Z`)
- [ ] Check for new migrations (`ls apps/*/migrations/`)
- [ ] Check for new settings in `.env.example`
- [ ] Check for new dependencies in `pyproject.toml`
- [ ] Run `make test` after merge
- [ ] Spot-check UI in dev before deploying
