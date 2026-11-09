---
name: downstream-release-migration
description: "Migrating a fork onto a new release — additive vs breaking changes, the false-test-result + removed-symbol traps, finding what each crossed version changes"
license: MIT
metadata:
  source: "docs/skills/downstream-release-migration.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
  scope: "fork-facing"
---

> Generated from `docs/skills/downstream-release-migration.md` by `make skills-index` — edit the source, not this file.

# Skill: Downstream Release Migration

How to migrate a project built on SmallStack onto a new
SmallStack release **safely** — knowing which changes are additive, which are breaking, and how
to get a *trustworthy* test result before you deploy.

This is the per-release companion to `integration-workflow.md` (which covers the generic
`git fetch upstream` / conflict-resolution mechanics) and `UPGRADING.md` at the repo root
(which lists breaking changes by version). Read this when you're crossing one or more releases,
not for a same-day patch.

> **Why this skill exists.** A real downstream merge (v0.11.3 → v0.11.13) reported
> `905 passed / 6 failed` — but **4 of the 6 were false failures** from the suite running under
> the wrong settings, and one breaking change (django-tables2 removal) wasn't recognized until
> a downstream app failed to import. Both are now preventable; this skill bakes the checks in.

---

## The procedure

```bash
cd ../<your-project>                    # the project you're upgrading
git fetch upstream
# Read what you're pulling: every version you cross (see "What your crossing changes")
git merge upstream/main
```

Resolve conflicts per the table in `integration-workflow.md`. Then, **before** trusting anything:

```bash
uv sync --all-extras
make migrate

# 1. Run the suite UNDER THE REAL TEST SETTINGS — a configured dev shell lies (see below).
uv run pytest --ds=config.settings.test

# 2. Look for downstream code that imports symbols a crossed release removed
#    (UPGRADING.md names them; v0.12's was django-tables2):
grep -rn "<removed symbol>" apps/

make lint
make run                                # spot-check UI before deploying
```

Only after a clean run under `--ds=config.settings.test` should you commit + deploy.

---

## The two recurring traps (always check these)

### 1. False test results — the suite runs under the wrong settings
A dev shell that exports `DJANGO_SETTINGS_MODULE=config.settings.development` (via `.env` +
direnv/IDE/`uv`) **beats** the pytest ini value, so `make test` silently runs under
*development* settings and produces red/green that doesn't match CI. Symptoms: mcp-logging or
explorer-discovery tests flip-flop; local green ≠ CI green.

- **v0.11.14+** pins `--ds=config.settings.test` in `pyproject.toml` `addopts`, so once you've
  merged that, `make test` is deterministic everywhere. If your downstream added a local
  Makefile workaround for this, it's now redundant (harmless — you can drop it).
- **Still on a pre-v0.11.14 base?** Always run `uv run pytest --ds=config.settings.test`
  manually to get the true result after a merge.

### 2. Removed public symbols break downstream imports silently
The base keeps its *own* apps green by migrating them in the same commit, so a removal doesn't
break the base — it breaks **your** app's imports on merge. Run the `grep` above for each
symbol `UPGRADING.md` lists as removed in a version you cross.

---

## What your crossing changes

Read these for **every** version between your base and the target, oldest first:

1. **`### Upgrading from X.Y`** at the top of each version's `CHANGELOG.md` entry (from 0.30.0
   on): one line per thing that changes a build.
2. **`UPGRADING.md`**, every section for those versions: who is affected, what changed, and the
   migration steps. v0.30.0's starts with an "at a glance" list.
3. **The diff itself**, for whatever the notes don't say:

```bash
B=v0.28.0; T=v0.30.0                                      # your base, your target
git diff $B $T -- config/settings/ docker-entrypoint.sh   # settings, INSTALLED_APPS, TASKS, CSP, entrypoint
git diff --stat $B $T -- 'apps/*/migrations/*'           # new migrations (and new apps)
git diff $B $T -- .env.example pyproject.toml            # new env vars, dependencies
```

Releases from 0.29 to 0.30 changed these for downstreams: the CSP's `script-src` (inline scripts
are blocked, with a stopgap), a new `apps.dashboards` app, a `webhooks` task queue with its own
entrypoint worker, queued account emails with `EMAIL_TIMEOUT=10`, and new settings. All are in
`UPGRADING.md` under v0.30.0.

**Older release lines.** v0.11 → v0.12 removed django-tables2 (`table_class` → `list_fields` /
`link_field` / `field_transforms` / `row_actions`, recipe in `UPGRADING.md`) and added the
status-monitoring subsystem (`merge-0.12.0.md`). v0.11.14 pinned `--ds=config.settings.test`.

---

## Verification (the "true result" gate)

A downstream migration is done when, **after merge**:

1. `uv run pytest --ds=config.settings.test` is green (not just `make test` in your shell).
2. The removed-symbol greps for every crossed version return nothing (or only sites you've
   migrated per `UPGRADING.md`).
3. `make lint` is clean and `make run` spot-checks render: the pages the crossed versions touched,
   and your own pages with controls (an inline script the CSP blocks fails without an error).
4. `make migrate` reports no unapplied migrations.

Then commit (`chore: Pull upstream SmallStack vX.Y.Z`) and deploy per `integration-workflow.md`.

---

## When a merge reveals an upstream gap

Per the fix-upstream pattern: if the migration surfaced a missing upgrade note, a bad default, or
a breaking change with no docs, **fix it in `smallstack/`** (add to `UPGRADING.md`, this skill, or
the code) and push — so the next downstream migration is smoother. That feedback loop is how this
skill got written.

## See also
- `integration-workflow.md` — generic pull / conflict-resolution / deploy mechanics
- `../../UPGRADING.md` — breaking changes + migration recipes, keyed by version
- `release-process.md` — how upstream cuts a release (the other side of this)
