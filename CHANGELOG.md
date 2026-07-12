# Changelog

All notable changes to SmallStack are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Breaking-change migration recipes live in [`UPGRADING.md`](UPGRADING.md).

## [Unreleased]

### Added
- `register_api_path` — let custom `@api_view` endpoints join the OpenAPI schema.
- Maintenance-window tooling for heartbeat/status: `manage.py maintenance` command and
  `apps/heartbeat/maintenance.py` (open a maintenance window / SLA-exclude a deploy).
- CSP: added `base-uri 'self'` and `object-src 'none'` directives (no inline-script trade-off).

### Security
- Fixed stored-XSS in the CRUD field-preview markdown renderer — arbitrary field content can no
  longer inject script. Raw HTML is neutralized (rendered as escaped text), dangerous link/image
  URL schemes (`javascript:`, `data:`, …) are blanked via a URL allowlist, and the extension set
  is restricted to `fenced_code`/`tables` (no `md_in_html` / `attr_list`). Regression-tested.
- Fixed stored-XSS in search-result snippets — the plain-text snippet is no longer rendered `|safe`.

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

[Unreleased]: https://github.com/emichaud/django-smallstack/compare/v0.12.3...HEAD
[0.12.3]: https://github.com/emichaud/django-smallstack/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/emichaud/django-smallstack/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/emichaud/django-smallstack/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/emichaud/django-smallstack/compare/v0.11.19...v0.12.0
