# Changelog

All notable changes to SmallStack are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Breaking-change migration recipes live in [`UPGRADING.md`](UPGRADING.md).

## [Unreleased]

### Added
- **Scheduler (`apps/scheduler/`)** — recurring background jobs over `django.tasks`
  (no Celery/Redis). Ships the `@scheduled` decorator (cron / interval / once,
  with calendar-aware intervals and anchors), DB-backed `ScheduledJob` schedules
  with idempotent code-sync, and a `run_due_jobs` tick with an **atomic claim**
  so concurrent triggers can't double-fire. Overlap guard (with a stale-run
  timeout so a dead worker can't wedge a schedule), catch-up policy, and run
  history linked to the task engine's `DBTaskResult`.
- **Scheduler surfaces** — themed `/smallstack/scheduler/` dashboard (stat cards,
  24h run timeline, upcoming + recent runs, per-job Run-now), a `ScheduledJob`
  CRUDView with REST (`enable_api`) + MCP (`list_schedules` … `delete_schedule`)
  + search, a dashboard widget, a `/status/` core monitor, and Explorer browsing.
- **Triggers** — `POST /smallstack/scheduler/tick/` (localhost-only, runs inside
  gunicorn), `manage.py run_due_tasks`, `manage.py scheduler_beat`; plus
  `manage.py prune_job_runs` history retention. Cron lines added to
  `scripts/smallstack-cron`.
- Settings: `SMALLSTACK_SCHEDULER_ENABLED`, `_STALE_RUN_SECONDS`,
  `_OVERDUE_GRACE_SECONDS`, `_FAILURE_EMAILS`. New dependency: `croniter`.
- Docs: `docs/skills/scheduler.md`; `@scheduled` flipped from "coming soon" to
  shipped in `CLAUDE.md`, `README.md`, `background-tasks.md`, `skills/README.md`.

## [0.13.5] - 2026-07-19

### Fixed
- **SQLiteFTSBackend.rebuild() deadlock** — Fixed "database is locked" error on models with >500 rows. 
  Root cause: iterator(chunk_size=500) kept read cursor open during writes. Solution: materialize pk list, 
  batch with explicit transactions. Approximately 50x faster; tested with 25,713+ rows.
- **SearchBuilder.transform_hit() call convention** — Fixed silent failure where custom variants returned 
  empty extra payload. Root cause: instance method called unbound on class (TypeError swallowed). 
  Solution: instantiate view before calling, matching pattern elsewhere. Enhanced error logging to 
  document contract.
- **PostgresFTSBackend.rebuild()** — Applied same deadlock fix as SQLite (consistent batching pattern).

### Documentation
- Added fixes/DOWNSTREAM-ISSUES.md documenting both bugs, root causes, and fixes.
- Clarified that filter_searchable_queryset and get_ranking_weights are dead code in v0.13.4; 
  use search_weight and post-filtering instead.

### Backward Compatible
- No API changes
- All fixes are transparent to downstream apps
- Required for any model with >500 rows + enable_search, or custom SearchBuilder.transform_hit()


## [0.13.4] - 2026-07-18

### Added
- **SearchBuilder — programmable search customization** (Phases 1-2, ~3,500 LOC): Optional SearchBuilder protocol 
  enables models to define custom search variants (admin, public, api, mcp, etc.) with computed fields, custom 
  display logic, cross-model orchestration, and automatic MCP tool generation per variant. Native dict serialization 
  (no DRF dependency). Full type hints and comprehensive testing.
- **Native search serialization** — 4 pure-Python dict functions (`serialize_search_hit`, `serialize_search_results`, 
  `serialize_search_config`, `serialize_all_search_configs`) for JSON-safe output. Supports variant-specific extra fields 
  with transparent flattening.
- **Search introspection API** — `SearchAPI` class with 5 methods (get_config, list_variants, search, search_and_filter, 
  get_output_schema) for high-level orchestration; `SearchOrchestrator` for multi-stage workflows and cross-model search.
- **Search variant caching** — In-memory config cache with 1-hour TTL and cache invalidation on view registration.
- **Per-variant MCP tools** — Auto-generated MCP tools for each search variant (search_model, search_model_summary, 
  search_model_admin, etc.) for agent orchestration.

### Fixed
- **F1 (BLOCKER)** — Instance method call on class; fixed by instantiating view_cls before calling get_search_variants().
- **F2 (MAJOR)** — Removed djangorestframework dependency; replaced with 4 native dict serialization functions.
- **F4 (MAJOR)** — Guarded 3 unguarded date_joined references in search examples; added missing email field to admin variant.
- **F5 (MAJOR)** — Fixed 252 ruff lint errors (226 W293 whitespace, 16 F401 unused imports, 9 I001 unsorted, 1 E501 line length).
- **F6 (MAJOR)** — Replaced broken DRF serializer tests with real native serializer tests; removed false pytest.skip guards.
- **F7 (OBSERVATION)** — Documented extra field flattening behavior and collision risk in serialize_search_hit() docstring.

### Technical Details
- All new code is fully typed (Python 3.10+ syntax: dict[str, Any], QuerySet, return types)
- 119 integration tests covering all variants, orchestration, caching, and admin integration
- Comprehensive documentation: RUNBOOK.md, TUTORIAL.md, ORCHESTRATION-GUIDE.md, and 2 AI skills
- Backward compatible: all SearchBuilder methods optional; existing search works unchanged
- No breaking changes to SearchBackend protocol or query() signature


## [0.13.3] - 2026-07-16

### Fixed
- **Runbook dark-mode CSS** — enhanced styling now correctly scoped to app theme (`html[data-theme="dark"]`) 
  instead of OS setting (`@media prefers-color-scheme`), ensuring enhancements apply on default dark mode 
  regardless of OS theme setting.
- **Seeder idempotency** — `seed_platform_runbook` command now properly assigns section before guard check, 
  preventing `IntegrityError` crashes on re-run; added comprehensive idempotency test.

## [0.13.2] - 2026-07-12

### Added
- **`sc` — a framework CLI** (`manage.py sc` / the `sc` console script): a fifth thin skin over the
  CRUDView registry, the same operations as web/REST/MCP. Resource verbs — `ls` (registered models +
  rows, with `-q`/`--filter`/`--order`/`--limit`), `get`, `describe`, `search`, and writes `new`/`set`/
  `rm` through the model's `form_class` validation + `log_write` audit (staff-gated like the MCP tools).
  Operational verbs — `doctor`/`backup`/`token`/`status`/`index` (thin fronts over the framework's
  management commands) plus `sc commands` discovery. `--json` on every read. Explorer-synthesized views
  mean it reaches every admin-registered model, not just hand-written CRUDViews. See
  `docs/skills/sc-cli.md`.

### Fixed
- **Bundled JS client** (`clients/js` v0.3.1): SSR-safe `localStorage` access — the client guards
  `localStorage` so it's safe to import in a server-side-rendering context.

## [0.13.1] - 2026-07-12

### Added
- **Bundled API clients** under `clients/`: a TypeScript/JavaScript SDK (`clients/js`, with built
  `dist/`) and a single-file Python client (`clients/python/smallstack_client.py`) for talking to the
  REST API from external apps. See `clients/README.md`.

## [0.13.0] - 2026-07-12

### Added
- **Runbook — a first-class dynamic-documents app** (`apps/runbook/`): versioned markdown documents
  with images, sections, keyword + full-text search, retention, subscriptions, and portable ZIP
  bundles — readable and writable from the web UI, a transport-agnostic service layer, REST, MCP,
  and a unix-style CLI. (Previously the standalone `smallstack-runbook` package; now permanent core.
  The `smallstack_runbook` DB label is preserved, so existing tables/migrations reuse as-is.)
- **Runbook CLI** (`manage.py runbook` / the `rb` console script): `ls`, `toc`, `find` (BM25-ranked
  search), `cat` (`<ref>@N` reads an earlier version), `write` (stdin), `cp`, `rm`, `restore`, `mv`,
  `revert`, `log`, `stat`, `mkdir`, `sections`, `publish`/`unpublish`. Every verb takes `--json`.
- **Runbook REST API**: full document lifecycle (`api/documents/…`, incl. `append`/`move`/`archive`/
  `unarchive`/`revert`/`copy`) plus an `api/runbooks/…` container resource (list/create, detail +
  table of contents, sections, publish/unpublish). All registered in the OpenAPI schema (Swagger/
  ReDoc) and ownership-scoped. `GET api/documents/?q=` is BM25-ranked (substring fallback).
- **Runbook MCP tools** + search-engine registration (`search_runbook_documents`, global omnibar).
- **Runbook dashboard widget** on the central `/smallstack/` dashboard (runbook + document counts).
- `api_doctor` now lists hand-registered (`register_api_path`) custom endpoints, so its inventory
  matches the OpenAPI schema (and warns on any `url_name` that no longer reverses).

### Changed
- Client-IP resolution is now proxy-aware and shared by the activity log and the django-axes login
  lockout. Behind a trusted reverse proxy (`TRUST_PROXY_HEADERS`, defaulted on in production for
  kamal-proxy) the real client is read from the rightmost, proxy-appended `X-Forwarded-For` entry
  (spoof-resistant); otherwise the unspoofable `REMOTE_ADDR` is used. One helper
  (`apps/smallstack/client_ip.py`) is the single source of truth.
- The markdown hardening from the CRUD field-preview is extracted into a reusable
  `harden_markdown_renderer()` and shared with the runbook renderer.

### Fixed
- **Stored XSS in runbook document rendering** — user- and AI-authored document bodies could inject
  `<script>` / `<img onerror>` / `javascript:` links that executed in a viewer's session. The
  renderer now escapes raw HTML and blanks dangerous URL schemes, and drops the unsafe `md_in_html`
  and `attr_list` extensions. Regression-tested.
- Runbook ZIP export silently omitted section-less ("loose") documents attached straight to a
  runbook — they are now included (loose docs at the archive root).
- Runbook CLI N+1 queries in `ls`, `toc`, and `sections`.
- MCP activity page: the filter `Apply`/`Reset` buttons now align with the control row.
- Silenced the django-axes INFO startup banner in development (it polluted piped CLI output).

### Security
- django-axes now resolves the real client IP behind kamal-proxy, so per-IP brute-force lockout is
  effective in production (previously every request keyed to the proxy's address, neutering it).

## [0.12.4] - 2026-07-11

### Security
- **Dependencies:** bumped Django (→6.0.7), Pillow (→12.3.0), starlette, pydantic-settings, pygments,
  and pytest to their fix releases — `pip-audit` goes from 13 known vulnerabilities to 0.
- Fixed stored-XSS in the CRUD field-preview markdown renderer — arbitrary field content can no
  longer inject script. Raw HTML is neutralized (rendered as escaped text), dangerous link/image
  URL schemes (`javascript:`, `data:`, …) are blanked via a URL allowlist, and the extension set
  is restricted to `fenced_code`/`tables` (no `md_in_html` / `attr_list`). Regression-tested.
- Fixed stored-XSS in search-result snippets — the plain-text snippet is no longer rendered `|safe`.
- CSP: added `base-uri 'self'` and `object-src 'none'` directives (no inline-script trade-off).

### Added
- `register_api_path` — let custom `@api_view` endpoints join the OpenAPI schema.
- Maintenance-window tooling for heartbeat/status: `manage.py maintenance` command and
  `apps/heartbeat/maintenance.py` (open a maintenance window / SLA-exclude a deploy).
- Per-app `README.md` files, plus `SECURITY.md` and this `CHANGELOG.md`.

### Fixed
- Ordering by a computed/non-DB column no longer 500s — a misconfigured `ordering_fields` (or a
  hand-crafted `?ordering=`) degrades to no-sort instead of raising `FieldError`.
- Search: a model registered *after* the search app's `ready()` (from a later app in
  `INSTALLED_APPS`) now gets its per-model `search_<plural>` MCP tool — registration is now
  independent of app order.
- OpenAPI `info.version` and `MCP_SERVER_VERSION` derive from the package version (new
  `SMALLSTACK_VERSION` setting) instead of a hardcoded `1.0.0`.
- Dev `SECRET_KEY` is persisted to a gitignored `.secret_key` so all local processes share one key —
  `screenshot_auth` sessions are no longer silently rejected on a fresh clone.

### Changed
- API-layer dedup: `json.loads` bodies via `_load_json_body`; the three HTML-pagination sites via
  `attach_display_helpers`; `_api_list` and the OpenAPI path builders slimmed via extracted helpers.
- Heartbeat: six function-based views moved to a shared `staff_required` decorator.
- Type hints completed on `apps/activity`, `apps/tasks`, `apps/profile`, and `apps/smallstack/displays.py`;
  narrowed/logged several broad `except` handlers.
- Standardized test layout (`accounts`/`heartbeat` → `tests/` packages); `apps/tasks` coverage 0% → 99%.
- Docs: unified "Coming soon" framing for `@scheduled` + vector search; completed the CLI reference.

## [0.12.3] - 2026

### Fixed
- Invisible status calendar/timeline cells on standalone status pages.

## [0.12.2] - 2026

### Changed
- Maintenance-aware status: uptime/SLA calculations exclude scheduled maintenance windows.

### Fixed
- Test-suite robustness improvements.

## [0.12.1] - 2026

### Added
- `merge-0.12.0` upgrade skill documenting the v0.12.0 migration path.

## [0.12.0] - 2026

### Added
- **Pluggable status monitoring system** — register a Service + Monitor to track a
  subsystem's uptime/health on `/smallstack/status/`; add status visualizations.
  See `docs/skills/status-monitors.md`.

### Changed
- MCP and Search are decoupled from the status system (independent enable flags).
- Daily-timeline "today" coloring and doctor-command flag-awareness fixes.

### Removed
- **django-tables2** and the public `apps.smallstack.tables` / `table_class` surface.
  Downstream projects importing these must migrate — see `UPGRADING.md`.

## [0.11.x] - 2026

Condensed highlights of the v0.11 series (see git history for per-patch detail):

### Added
- Account invites by email + passwordless code login with branded emails (`apps/accounts`).
- Username-or-email login (`EmailOrUsernameBackend`).
- `usermanager`: password-on-create, edit actions, and guardrails.
- Consolidated dashboard stat cards into one `{% stat_card %}` standard with drill-down modals.
- API endpoints admin page; clickable list rows; table pagination.
- Editorial "Getting Started" redesign; apps-dropdown redesign; Search section on Home.

### Fixed
- **v0.11.14** — pinned test settings to `config.settings.test` (`--ds` in `addopts`) so the
  suite no longer silently ran under dev settings; hermetic dev-superuser test; v0.12 upgrade note.
- **v0.11.13** — platform re-audit hardening: security fixes (OAuth scope→role capping, token
  scope, backups, allowed hosts), Postgres fixes, **GitHub Actions CI** (SQLite + Postgres matrix
  + ruff), and the django-tables2 removal groundwork.
- Django-6 `log_action` breakage that broke programmatic API/MCP write audit logging.
- Explorer detail grid rendering every boolean as ✓ regardless of value.

## Earlier releases (0.8.x – 0.10.x)

See the git tag history (`git tag`) and `ai_cowork/audit_history/` for the full record of the
v0.8–v0.10 API-server, modern-dark-theme, search, MCP, and Postgres eras.

[Unreleased]: https://github.com/emichaud/django-smallstack/compare/v0.13.2...HEAD
[0.13.2]: https://github.com/emichaud/django-smallstack/compare/v0.13.1...v0.13.2
[0.13.1]: https://github.com/emichaud/django-smallstack/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/emichaud/django-smallstack/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/emichaud/django-smallstack/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/emichaud/django-smallstack/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/emichaud/django-smallstack/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/emichaud/django-smallstack/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/emichaud/django-smallstack/compare/v0.11.19...v0.12.0
