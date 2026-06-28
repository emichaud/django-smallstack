# Skill: Merging the v0.12.0 release into an older SmallStack project

How to bring a downstream project (smallstack_web, opshugger, or any clone) **up to
v0.12.0** when it's on an older base. v0.12.0 has two distinct parts that need
different handling:

1. **`django-tables2` removed** — the one **BREAKING** change. Already fully
   documented; don't re-derive it here (see below).
2. **The pluggable status-monitoring subsystem** — large but **additive**. This skill
   focuses on its integration points, because they're the non-obvious part of the
   merge (new settings, route gating, app-load ordering, an autodiscover that moved).

This is the per-feature companion to:
- `downstream-release-migration.md` — the generic "migrate onto a new release" procedure + the false-test-result / removed-symbol traps. **Read it first.**
- `integration-workflow.md` — generic `git fetch upstream` / conflict mechanics.
- `../../UPGRADING.md` — breaking changes keyed by version (the tables2 recipe lives here).

> Read this when a merge to v0.12.0 brings in the `/status/` system and you're
> reconciling a *customized* settings/urls/apps layout. For the mechanics of the
> merge itself, defer to the two skills above.

---

## Part 1 — the BREAKING change (handle first)

`django-tables2` is gone (`apps/smallstack/tables.py` deleted, dep dropped). If your
app defined a `tables.Table` + `table_class = …`, it fails to import after `uv sync`.

```bash
grep -rn "django_tables2\|apps.smallstack.tables\|table_class" apps/
```

Migrate each hit to the declarative CRUDView attributes per **`UPGRADING.md` →
v0.12.0** (`list_fields` / `link_field` / `field_transforms` / `row_actions`). The
"this release line" table in `downstream-release-migration.md` has the same guidance.
Do this **before** trusting any test run — it's an import-time failure that masks
everything else.

---

## Part 2 — the status-monitoring subsystem (additive)

The `/smallstack/status/` overview, the branded public `/status/` board, per-monitor
SLA, Site/External monitors, and the surface toggles. It's additive — but it touches
shared config files, so a customized downstream has a few merge points to get right.

### What it adds (so you know what should arrive in the merge)

- **New modules** (take wholesale, rarely conflict): `apps/heartbeat/` gains
  `monitors.py`, `surfaces.py`, `status.py`, `visualizations.py`, the
  `MonitoredEndpoint` + `MonitoredSurface` models, status views/templates, and
  **migrations `0007`–`0011`**. `apps/smallstack/` gains `autodiscover.py`,
  `monitors.py`, `visualizations.py`. `apps/{api,mcp,search}/monitors.py` register
  each surface as a status monitor.
- **The `Status` sidebar entry** registers itself from `apps/heartbeat/apps.py:ready()`
  — no nav/template edit needed.

### The integration points that actually need attention

| File | What changed | Downstream action |
|---|---|---|
| **`config/settings/base.py`** — `INSTALLED_APPS` | The subsystem registers from `apps.heartbeat / mcp / api / search` `ready()`. They're already in a SmallStack base; just confirm none were removed. | Confirm `apps.heartbeat`, `apps.mcp`, `apps.api`, `apps.search` are all present. |
| **`config/settings/smallstack.py`** | Three new **surface toggles** (`SMALLSTACK_PUBLIC_STATUS_ENABLED`, `SMALLSTACK_API_ENABLED`, `SMALLSTACK_MCP_ENABLED`), all default `True`. The old `SMALLSTACK_STATUS_DEV_LINKS` is **removed**. | Take the new flags. If your fork added `SMALLSTACK_STATUS_DEV_LINKS`, drop it (the dev hub it gated is gone). |
| **`config/urls.py`** | Adds the public `status/`, `status/json/`, and `status/maintenance/*` routes, **and** wraps the `/api/*` and `/mcp` route blocks in `if getattr(settings, "SMALLSTACK_API_ENABLED"/"…MCP_ENABLED", True)`. | If you customized `urls.py`, take upstream's structure (incl. the two `if` gating blocks) and re-apply your project routes. Missing the gating blocks just means the toggles won't work — not a crash. |
| **`apps/smallstack/apps.py`** (`SmallStackConfig.ready()`) | Now calls `autodiscover_app_modules(("views",))` **unconditionally** — this imports every app's `views.py` so `CRUDView._registry` is populated for Search, the status monitors, MCP, and Explorer. In *older* bases this discovery rode on `apps/mcp/apps.py`. | **Critical: if your fork overrode `apps/smallstack/apps.py`, you MUST keep the `autodiscover_app_modules(("views",))` call.** Without it, Search and the status overview register nothing (see Gotcha 1). |
| **`apps/mcp/apps.py`** | `ready()` now autodiscovers only `mcp_tools` (the `views` discovery moved to the core, above). | Take upstream. Conflict only if you customized MCP startup. |

`apps/website/` is yours — keep it. The status system doesn't touch it.

---

## Procedure

For a fork that tracks upstream:

```bash
cd ../<downstream>
git fetch upstream
gh release view v0.12.0 --repo emichaud/django-smallstack   # read the notes
git merge upstream/main
# resolve the files in the table above (most conflicts are settings/urls/apps.py)
```

For a **detached** clone (`.git` was removed at setup — the common case), there's no
`upstream` to merge; apply the release as a diff against a reference checkout:

```bash
git clone https://github.com/emichaud/django-smallstack /tmp/ss-0.12.0
# diff the shared framework dirs and port changes (NOT apps/website — that's yours)
diff -ru apps/heartbeat /tmp/ss-0.12.0/apps/heartbeat
diff -ru config /tmp/ss-0.12.0/config
# bring the new files over wholesale, then reconcile the shared-config files by hand
```

Then, for either path:

```bash
uv sync --all-extras
make migrate            # applies heartbeat 0007–0011 (MonitoredEndpoint/Surface + monitor_key)
```

---

## Verification (the "true result" gate)

```bash
uv run pytest --ds=config.settings.test    # not bare `make test` — see downstream-release-migration.md trap #1
make lint
uv run python manage.py check
uv run python manage.py api_doctor          # expect green (or "disabled" if you set the toggle off)
uv run python manage.py mcp_doctor
make run                                    # then load the pages below
```

Manual spot-check:
- `/smallstack/status/overview/` — Site / Site Monitors / External Monitors render; Site card shows core services.
- `/status/` (logged out) — the branded public board loads.
- Search still works (`/smallstack/search/`) — the canary for Gotcha 1.

---

## Gotchas specific to this merge

**1. Search / status overview empty after merge → the `views` autodiscover didn't land.**
If Search reports "No models indexed" and the status overview is missing monitors,
your merged `apps/smallstack/apps.py` is missing the
`autodiscover_app_modules(("views",))` call in `ready()`. That call is what imports
every app's `views.py` to populate `CRUDView._registry`; in older bases it lived in
`apps/mcp/apps.py`, so a 3-way merge that kept your old core `apps.py` drops it.
Re-add it. (This is the exact coupling v0.12.0 fixed — disabling MCP must not break
Search.)

**2. The surface toggles are read at startup, not per request.** Setting
`SMALLSTACK_MCP_ENABLED=False` etc. in `.env` requires a **restart**; they gate URL
registration at import time. See `settings.md` → "Surface toggles".

**3. `mcp_doctor` / `api_doctor` reporting "disabled" is not a failure.** If you ship
with a surface toggled off, the doctors print a green "disabled via
SMALLSTACK_X_ENABLED" line — that's expected, not a regression.

**4. Don't carry `SMALLSTACK_STATUS_DEV_LINKS`.** The temporary dev-links hub it
gated was removed in this line; a stale reference in your settings is harmless but
dead.

---

## When the merge reveals an upstream gap

Per the fix-upstream pattern: if this merge surfaced a missing note or a bad default,
fix it in `smallstack/` (this skill, `UPGRADING.md`, or the code) and push — so the
next downstream merge is smoother.

## See also
- `downstream-release-migration.md` — the generic release-migration procedure + traps
- `integration-workflow.md` — upstream/downstream merge + deploy mechanics
- `../../UPGRADING.md` — the v0.12.0 `django-tables2` migration recipe
- `status-monitors.md` — how the status subsystem works once it's merged in
- `settings.md` → "Surface toggles" — the three feature flags
