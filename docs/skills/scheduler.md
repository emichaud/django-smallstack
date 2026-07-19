---
title: Scheduler
description: Recurring background jobs — the @scheduled decorator, the scheduler UI, and how the tick fires.
---

# Skill: Scheduler (`apps/scheduler/`)

SmallStack's scheduler runs tasks on a **repeating** cadence. It builds directly
on the `django.tasks` engine (see `background-tasks.md`) — no Celery, Redis, or
worker fleet. The scheduler owns *timing, overlap, and history*; the task engine
owns *execution and results*. The two are joined by a `task_result_id`.

> **When to reach for it:** you have a task that must run every N minutes/hours,
> on a cron expression, or once at a future time — e.g. an ETL fetch, a nightly
> rollup, a digest email. For one-shot "do this now, off the request thread,"
> just `.enqueue()` a task (see `background-tasks.md`); no schedule needed.

## Two ways to create a schedule

### 1. `@scheduled` in code (source = `code`)

Declare the cadence next to the task. Apply `@scheduled` **above** `@task`:

```python
# apps/sportstats/tasks.py
from django.tasks import task
from apps.scheduler import scheduled

@scheduled(cron="15 * * * *", name="Hourly boxscore fetch")   # :15 past each hour
@task
def fetch_boxscores():
    raw = fetch_provider()      # network I/O — must not block a request
    load_into_db(raw)
    return {"loaded": len(raw)}
```

Cadence options (exactly one):

| Argument | Meaning | Example |
|---|---|---|
| `every="5m"` | interval; units `s/m/h/d/w` (fixed) or `mo/y` (calendar) | `every="90d"`, `every="1y"` |
| `cron="0 6 * * *"` | 5-field cron, evaluated in `timezone=` (DST-correct) | `cron="15 * * * *"` |
| `at=<datetime>` | run once at a specific time | — |

Other kwargs: `anchor="12-25"` (phase-lock an interval — "every 1y from Dec 25"),
`timezone="America/New_York"`, `queue_name=`, `catch_up="run_once"|"skip"`,
`allow_overlap=False`, plus any task kwargs (stored and passed to `.enqueue()`).

On boot, `apps.py:ready()` autodiscovers each app's `schedules.py`/`tasks.py` and
**idempotently syncs** every `@scheduled` spec into a `source="code"`
`ScheduledJob` row. The *cadence* is refreshed from code each deploy; the
`enabled` flag stays under user control (pause survives a redeploy). Removing the
decorator + redeploying retires the code declaration (the row can then be
disabled/deleted from the UI).

### 2. The UI (source = `ui`)

`/smallstack/scheduler/jobs/new/` — a themed form (validated, with a next-run
preview). Fully user-owned. The same model is exposed over **REST**
(`enable_api`) and **MCP** (`list_schedules` / `get_schedule` / `create_schedule`
/ `update_schedule` / `delete_schedule`), so an agent can manage schedules
through the same audited path a human uses.

## How the tick works

One core routine — `services.run_due_jobs()` — selects enabled jobs whose
`next_run_at <= now`, **atomically claims** each (a conditional `UPDATE` that
advances `next_run_at`, so two concurrent ticks can never double-fire), then
enqueues the task and records a `ScheduledJobRun`. It is driven by one of three
interchangeable triggers — **use exactly one per deployment:**

| Trigger | Use |
|---|---|
| `POST /smallstack/scheduler/tick/` (localhost-only) | **Default.** One line in `scripts/smallstack-cron`; runs inside gunicorn → no SQLite lock contention. |
| `manage.py run_due_tasks` | System cron / systemd timer path. |
| `manage.py scheduler_beat` | Foreground 60s loop for `make run` / dev. |

The claim guard makes an accidental second trigger *safe* (it just no-ops), but
running two on purpose only wastes work.

## Policies worth knowing

- **Overlap** (`allow_overlap=False`, the default): skip a fire while the
  previous run is still unfinished. A run older than
  `SMALLSTACK_SCHEDULER_STALE_RUN_SECONDS` (default 24h) is treated as abandoned,
  so a dead worker can never permanently wedge a schedule.
- **Catch-up** after downtime: `catch_up="run_once"` (default) fires **once** and
  resumes; `catch_up="skip"` skips the missed window entirely. Neither backfills
  every missed interval.
- **Failure email**: set `SMALLSTACK_SCHEDULER_FAILURE_EMAILS` to notify on a
  failed run (reuses `send_email_task`).
- **Retries**: currently lean on `django.tasks`' own retry semantics. Per-schedule
  `max_retries` is a reserved field (not yet enforced).

## Run lifecycle (why a just-run job shows `queued`)

A `ScheduledJobRun` moves through two stages, and they're driven by **different**
steps — this trips up first-time users:

1. **Enqueue** (the tick, `run_due_jobs`): a run is recorded as **`queued`** the
   moment the task is enqueued. The tick's job ends here.
2. **Reconcile** (`reconcile_run_outcomes`): a *later* pass reads the task
   engine's `DBTaskResult` and promotes the run to **`success`**/**`failed`**,
   copying the task's **return value** (success) or the **exception line**
   (failure) onto `run.message` — which the dashboard shows under the status.

Reconcile runs at the **start of each tick** and on **every dashboard load**. So
right after `scheduler_beat --once` + `db_worker`, the run still reads `queued`
(the worker finished *after* that tick's reconcile) — open the dashboard, or run
one more tick, and it flips to `success`/`failed`. The task's return value is
**not** stored on the run until reconcile; it lives on `DBTaskResult` until then.

## Testing schedules

Under `config.settings.test` the task backend is `ImmediateBackend`, so
`.enqueue()` runs the task **inline** (no worker). Three patterns:

```python
# 1. Unit-test the raw function — no queue at all:
result = my_task.func(keep_days=30)          # .func is the undecorated callable
assert result == {"deleted": 3}

# 2. Exercise the scheduler path (enqueue + record):
from apps.scheduler import services
services.run_due_jobs()                       # enqueues due jobs → runs record as 'queued'

# 3. Force terminal status in a test (no real worker):
services.reconcile_run_outcomes()             # promotes queued → success/failed
run.refresh_from_db(); assert run.status == "success"
```

To assert a **failure** path, drive a task that raises; to assert a **failure
email**, patch the *whole* task object, not its method —
`mock.patch("apps.tasks.tasks.send_email_task")` then
`.enqueue.assert_called_once()` (patching `send_email_task.enqueue` directly
raises a `TypeError` on teardown because it's a `django.tasks.Task`, not a plain
object). Ready-made examples live in `apps/scheduler/tests/`.

## Local testing

```bash
uv run python manage.py scheduler_beat --once     # tick: enqueue due jobs (runs = queued)
uv run python manage.py db_worker                 # drain the queue (task runs)
uv run python manage.py scheduler_beat --once     # tick again: reconcile → success/failed
uv run python manage.py run_due_tasks             # cron-path equivalent (enqueue + reconcile)
```

Then watch `/smallstack/scheduler/` — stat cards, the 24h run timeline, upcoming
runs, recent runs (with each run's **return-value summary** under its status),
and a per-job **Run now**. The scheduler also registers a core status monitor on
`/smallstack/status/` that trips if an enabled job is overdue (a proxy for "the
tick isn't firing") or if the recent failure rate spikes.

## Files

```
apps/scheduler/
  models.py         # ScheduledJob, ScheduledJobRun
  decorators.py     # @scheduled + registry
  registry.py       # autodiscover + idempotent code-job sync
  schedules.py      # next_run(): once | interval(+anchor) | cron  (croniter)
  services.py       # run_due_jobs(): claim, overlap, catch-up, enqueue, record
  views.py          # CRUDView + dashboard + tick endpoint + run-now
  dashboard_widgets.py / monitors.py / explorer.py
  management/commands/{run_due_tasks,scheduler_beat,prune_job_runs}.py
```

The design rationale + the concurrency-claim discussion live in
`ai_cowork/plans/scheduler-spec.md`.
