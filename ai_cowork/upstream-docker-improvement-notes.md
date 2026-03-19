# [ARCHIVED] Upstream Docker Improvement Notes (from truenorth validation)

> **Status:** Resolved. SQLite permissions fixed in Dockerfile, `.env` step added to README, versions current at v0.8.8. Worker entrypoint duplication is a known minor issue — functional as-is.

Date: 2026-03-15

## Context

Validated a downstream project (`truenorth`) using the included SmallStack Docker flow and documented friction for same-day deploy use.

## High-value improvements

1. Document mandatory `.env` bootstrap step
- Current issue: `docker compose config` / `docker compose up` fails immediately if `.env` does not exist.
- Improvement: in README + docker docs, add first step:
  - `cp .env.example .env`

2. Add explicit local port override guidance
- Current issue: `8010` frequently collides with other local projects.
- Improvement: add `docker-compose.override.yml` example for alternate host port.

3. Harden SQLite startup permission handling
- Current issue: fresh volume can produce `OperationalError: unable to open database file` under non-root runtime.
- Improvement options:
  - In entrypoint, ensure `dirname(DATABASE_PATH)` exists and is writable; fail with clear diagnostics.
  - Add one-time init container/script to set ownership on mounted db path.

4. Split web and worker startup responsibilities
- Current issue: worker uses same entrypoint and repeats migrations/collectstatic/supercronic setup before running db worker.
- Improvement: add role-based entrypoint behavior, e.g.:
  - web: migrations + collectstatic + ensure_superuser + app server + cron
  - worker: db worker only (and maybe lightweight readiness wait)

5. Refresh version statements in docs
- Current issue: downstream docs/readme can drift from lockfile/runtime versions.
- Improvement: align stack/version sections with actual dependency lock data and supported Python versions.

## Suggested acceptance checks

- `docker compose up --build -d` works from clean clone after only `cp .env.example .env`
- `/health/` returns `200` without manual permission fixes
- Worker starts without running full web boot sequence
- README/docker docs include tested commands for alternate local ports
