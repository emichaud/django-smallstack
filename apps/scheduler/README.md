# scheduler — recurring background jobs

DB-backed scheduler over the `django.tasks` engine (no Celery/Redis). Decorate a
`@task` with `@scheduled(...)` — or create a schedule in the `/smallstack/scheduler/`
UI — and it runs on a cron/interval/once cadence. The scheduler owns *timing,
overlap, and history*; the task engine owns *execution and results*, joined by a
`task_result_id`.

**Status:** Framework-provided. Enabled by default (`SMALLSTACK_SCHEDULER_ENABLED`);
harmless with zero jobs.

**Surfaces:** themed dashboard (stat cards, 24h timeline, upcoming + recent, Run-now),
a `ScheduledJob` CRUDView (**list + update only** — jobs are code-owned) with REST
(`enable_api`) + MCP (`list_schedules`, `update_schedule`) + search, a `/status/` core
monitor, and a `/smallstack/` widget.

**Triggers (use exactly one per deployment):** `POST /smallstack/scheduler/tick/`
(localhost-only, runs inside gunicorn — the default cron line), `manage.py
run_due_tasks` (system cron), or `manage.py scheduler_beat` (dev loop). Plus
`manage.py prune_job_runs` for history retention.

**Key files:** `models.py` (ScheduledJob/ScheduledJobRun), `decorators.py`
(`@scheduled`), `registry.py` (autodiscover + idempotent sync), `schedules.py`
(next-run math), `services.py` (`run_due_jobs` — the atomic claim, overlap,
catch-up), `views.py`, `monitors.py`.

**See:** [`../../docs/skills/scheduler.md`](../../docs/skills/scheduler.md) ·
design rationale in `ai_cowork/plans/scheduler-spec.md`.
