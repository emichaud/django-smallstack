---
name: integration-workflow
description: "Pulling upstream SmallStack into a fork and redeploying — remote setup, the conflict-resolution table, post-merge verification"
license: MIT
metadata:
  source: "docs/skills/integration-workflow.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
  scope: "fork-facing"
---

> Generated from `docs/skills/integration-workflow.md` by `make skills-index` — edit the source, not this file.

# Skill: Integration Workflow

How to pull SmallStack upstream changes into downstream projects and deploy.

## Overview

SmallStack is an upstream package. Downstream projects clone it and add their own business logic. This workflow covers pulling updates, resolving conflicts, and redeploying.

## Your Downstream Projects

Keep the map of your own projects in *your* repo's `CLAUDE.md` (or a project-local skill), not here — this
file ships to every fork. The shape worth recording:

| Project | Directory | Deployment | Purpose |
|---------|-----------|------------|---------|
| `<name>` | `../<name>/` | `<host or kamal destination>` | `<what it is>` |

Throughout this file, `../<your-project>` stands for one of those checkouts.

## Pull Upstream Updates

### First-Time Setup

If the downstream project doesn't have an upstream remote:

```bash
cd ../<your-project>
git remote add upstream https://github.com/emichaud/django-smallstack.git
git fetch upstream
```

### Regular Pull

```bash
cd ../<your-project>
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
| `docs/skills/README.md`, `docs/skills/index.json` | Take upstream (`git checkout --theirs`), then `make skills-index`. Keep *your* skill rows in `docs/skills/local.md`, which upstream never ships — see below |
| `docs/skills/release-process.md` | Take upstream — it documents upstream's own release ritual, not yours. Keep your release doc under your own name and register it in `local.md` |

### Keep the Typing Gate

Upstream's `make lint` runs **mypy + django-stubs** (the `[tool.mypy]` block in `pyproject.toml`),
and the apps listed under `[[tool.mypy.overrides]]` are checked strictly — an unannotated function
there fails lint. A downstream has to *carry* that gate or its own code drifts silently: the global
config is lenient on purpose (`check_untyped_defs = false`), so a function with no annotations is
simply not checked until someone annotates it, at which point every accumulated error appears at
once. That is not an upstream setting misbehaving; it is the absence of the gate.

On every pull, check three things:

```bash
grep -n "tool.mypy" pyproject.toml          # the block + the overrides survived the merge
grep -n "mypy" Makefile                     # `lint:` still runs `uv run mypy`
uv run mypy                                 # green before you commit the merge
```

A clone from before v0.9 never had the gate at all. Add the `[tool.mypy]` block and the
`uv run mypy` line to `lint:` from upstream, then run `make typecheck-strict` to see how far your
own apps are from joining the ratchet — add each one to the overrides list the moment it reaches
zero, and keep your new apps on that list from day one.

### Keep Your Own Skills Out of the Conflict Zone

Upstream's skill index (`docs/skills/README.md` → generated `docs/skills/index.json`) is upstream-tracked, so
registering your project's own skill files there means a conflict on every pull. Put them in
**`docs/skills/local.md`** instead — same table format, upstream ships no such file:

```markdown
## Our Skills

| File | Description |
|------|-------------|
| [upstream-workflow.md](upstream-workflow.md) | **(forks / downstream)** How *this* project pulls upstream and cuts releases |
| [billing.md](billing.md) | Our Stripe integration, plan gating, dunning |
```

Then `make skills-index`. Those rows land in `index.json` tagged `"origin": "fork-local"`, so an agent
consulting the index finds *your* skills alongside upstream's — which is the whole point: a skill file that
`CLAUDE.md` references but no index knows about sends agents to the neighbouring (wrong) skill instead.
`make lint` fails on a skill file registered in neither table, so this can't silently rot.

Rows upstream marks **(upstream repo only)** — `release-process.md` today — describe upstream's own process
and do not apply to your project. Write your own and register it in `local.md`.

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

### Kamal Deployment

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
