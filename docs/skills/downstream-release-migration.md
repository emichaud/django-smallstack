# Skill: Downstream Release Migration

How to migrate a downstream project (smallstack_web, opshugger, or any clone) onto a new
SmallStack release **safely** — knowing which changes are additive, which are breaking, and how
to get a *trustworthy* test result before you deploy.

This is the per-release companion to `integration-workflow.md` (which covers the generic
`git fetch upstream` / conflict-resolution mechanics) and `UPGRADING.md` at the repo root
(which lists breaking changes by version). Read this when you're crossing one or more releases,
not for a same-day patch.

> **Why this skill exists.** A real smallstack_web merge (v0.11.3 → v0.11.13) reported
> `905 passed / 6 failed` — but **4 of the 6 were false failures** from the suite running under
> the wrong settings, and one breaking change (django-tables2 removal) wasn't recognized until
> a downstream app failed to import. Both are now preventable; this skill bakes the checks in.

---

## The procedure

```bash
cd ../<downstream>                      # smallstack_web | opshugger
git fetch upstream
gh release view vX.Y.Z --repo emichaud/django-smallstack   # read what you're pulling
git merge upstream/main
```

Resolve conflicts per the table in `integration-workflow.md`. Then, **before** trusting anything:

```bash
uv sync --all-extras
make migrate

# 1. Run the suite UNDER THE REAL TEST SETTINGS — a configured dev shell lies (see below).
uv run pytest --ds=config.settings.test

# 2. Look for downstream code that imports symbols this release removed.
grep -rn "django_tables2\|apps.smallstack.tables\|table_class" apps/

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
break the base — it breaks **your** app's imports on merge. Run the `grep` above. The current
release line has already removed `django-tables2` (see next section).

---

## This release line: what to do

The django-tables2 removal is the one breaking change; everything else is additive or cosmetic.

| Change | Type | Downstream action |
|---|---|---|
| **django-tables2 removed** (`apps/smallstack/tables.py` deleted; `django_tables2` dropped from deps) — already on `main`, labeled v0.12.0 in `UPGRADING.md` | **BREAKING** | If any of your CRUDViews use `table_class` or import `apps.smallstack.tables` (`ActionsColumn`/`BooleanColumn`/`DetailLinkColumn`), they fail to import. Follow the `table_class → list_fields`/`link_field`/`field_transforms`/`row_actions` recipe in **`UPGRADING.md`** (root). Run the grep to find sites. |
| **Test-settings pin + hermetic dev-superuser test** (v0.11.14) | Fix | None. After merge `make test` is settings-deterministic; drop any local Makefile `--ds` workaround. |
| **API admin "Endpoints" page** (new tab on `/smallstack/api/` — services links + enabled-models table) | Additive | None. New view/url/template. *Only* if you customized `apps/api/templates/api/admin/_nav.html` or `health.html`, take upstream and reapply your changes (the nav gained a third tab). |
| **MCP activity filter buttons + placeholder fix** (`apps/mcp/templates/mcp/admin/activity.html`) | Cosmetic | Take upstream. Conflict only if you edited that template. |
| **Pluggable status-monitoring subsystem** (`/smallstack/status/` + public `/status/` board, Site/External monitors, per-monitor SLA, surface toggles) | Additive (touches shared config) | Read **`merge-0.12.0.md`** — it covers the integration points (surface-toggle settings, `config/urls.py` route gating, the `views` autodiscover that moved to `SmallStackConfig.ready()`, heartbeat migrations `0007`–`0011`). The one trap: keep the autodiscover call if you overrode `apps/smallstack/apps.py`, or Search goes empty. |

---

## Verification (the "true result" gate)

A downstream migration is done when, **after merge**:

1. `uv run pytest --ds=config.settings.test` is green (not just `make test` in your shell).
2. `grep -rn "django_tables2\|apps.smallstack.tables\|table_class" apps/` returns nothing (or
   only sites you've migrated per `UPGRADING.md`).
3. `make lint` is clean and `make run` spot-checks render (load `/smallstack/api/` and any page
   whose CRUDView you migrated off `table_class`).
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
