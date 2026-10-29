---
name: background-tasks
description: "Django Tasks framework with django-tasks-db backend"
license: MIT
metadata:
  source: "docs/skills/background-tasks.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/background-tasks.md` by `make skills-index` — edit the source, not this file.

# Skill: Background Tasks

This skill describes how to create and run background tasks in SmallStack using Django's built-in Tasks framework with the `django-tasks-db` backend.

## Overview

SmallStack uses Django 6's native `django.tasks` framework with the `django-tasks-db` database backend. Tasks are stored in the database and processed by a separate worker process. No Redis or Celery required.

> **Recurring scheduling ships in `apps/scheduler/`.** The queue itself is *one-shot* — you `.enqueue()` a task and a worker runs it once. To run a task on a **repeating** cadence, decorate it with `@scheduled(...)` (or create a schedule in the `/smallstack/scheduler/` UI). The scheduler decides *when* to enqueue and hands the actual execution to this same task engine. See **`docs/skills/scheduler.md`** for the full guide.

> **Reliability is layered on top of the engine** (`apps/tasks/`): SmallStack's `db_worker` keeps a **worker heartbeat** and **reaps tasks whose worker died** (no more rows stuck `RUNNING`), and tasks can opt into **retries with backoff** via `@retry_policy`. See [Reliability: lost tasks and retries](#reliability-lost-tasks-and-retries) below.

## File Locations

```
apps/tasks/
├── tasks.py          # Task definitions (examples; edit freely)
├── reliability.py    # @retry_policy, maybe_retry, chain_outcome, repair sweep
├── reaper.py         # Fails RUNNING tasks whose worker died (WorkerLost)
├── heartbeat.py      # Worker-side: register, beat, reap, mark stopped
├── signals.py        # task_finished receiver → retry a failed attempt
├── exceptions.py     # WorkerLost (recorded, never raised)
├── models.py         # WorkerHeartbeat, TaskAttempt
├── management/commands/
│   ├── db_worker.py  # Shadows django-tasks-db's db_worker (+ heartbeat)
│   └── reap_tasks.py # Manual reaper pass (--dry-run)
├── apps.py           # Connects tracing + retry receivers in ready()

config/settings/base.py        # TASKS configuration
config/settings/smallstack.py  # SMALLSTACK_TASKS_* reliability settings
docker-compose.yml             # Worker service definition
```

## Configuration

In `config/settings/base.py`:

```python
TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}
```

## Defining Tasks

Use the `@task` decorator from `django.tasks`:

```python
# apps/tasks/tasks.py (or any app's tasks.py)

from django.tasks import task

@task(queue_name="email")
def send_email_task(recipient, subject, message):
    """Send a plain-text email in the background."""
    from django.core.mail import send_mail
    return send_mail(subject=subject, message=message,
                     from_email=None, recipient_list=[recipient])

@task(queue_name="email")
def send_html_email_task(recipient, subject, template, context=None):
    """Send an HTML email using a Django template."""
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    html = render_to_string(template, context or {})
    email = EmailMultiAlternatives(subject=subject, body=subject,
                                   from_email=None, to=[recipient])
    email.attach_alternative(html, "text/html")
    return email.send()

@task(priority=5)
def process_data_task(data, operation="transform"):
    """Process data in the background."""
    # All arguments must be JSON-serializable
    return {"processed": True, "data": data}

@task(takes_context=True)
def task_with_context(context, message):
    """Access task metadata via context."""
    print(f"Task {context.task_result.id}, attempt {context.attempt}")
    return {"status": "done"}
```

### Task Decorator Options

| Option | Description |
|--------|-------------|
| `queue_name="email"` | Route to a specific queue (default: `"default"`) |
| `priority=5` | Higher priority tasks run first |
| `takes_context=True` | First argument receives `TaskContext` with metadata |

## Enqueuing Tasks

```python
from apps.tasks.tasks import send_email_task

# Enqueue for background processing
result = send_email_task.enqueue(
    recipient="user@example.com",
    subject="Hello",
    message="This is a test."
)

# Send to multiple recipients in a single task
result = send_email_task.enqueue(
    recipient=["owner@example.com", "backup@example.com"],
    subject="New order",
    message="Order #1234 received."
)

# Check status later
result.refresh()
print(result.status)  # SUCCESSFUL, RUNNING, or FAILED
```

**Tip:** `send_email_task` accepts a single string or a list of strings. Prefer passing a list over looping and enqueuing one task per recipient — it's one task, one SMTP call, one row in the task table.

### HTML Email

Use `send_html_email_task` to send a rendered Django template as an HTML email. If a matching `.txt` template exists alongside the HTML template, it's automatically used as the plain-text fallback.

```python
from apps.tasks.tasks import send_html_email_task

send_html_email_task.enqueue(
    recipient="user@example.com",
    subject="Your monthly report",
    template="email/monthly_report.html",
    context={"user_name": "Alice", "total": 42},
)
```

| Argument | Required | Description |
|----------|----------|-------------|
| `recipient` | Yes | Email address (string) or list of addresses |
| `subject` | Yes | Email subject line |
| `template` | Yes | Path to the HTML template (e.g. `"email/invoice.html"`) |
| `context` | No | Dict of template context variables (default: `{}`) |
| `from_email` | No | Sender address (default: `DEFAULT_FROM_EMAIL`) |

**Plain-text fallback:** For `email/invoice.html`, the task looks for `email/invoice.txt`. If found, it's rendered with the same context and attached as the plain-text body. If not found, the subject line is used as fallback.

## Running the Worker

### Development

```bash
uv run python manage.py db_worker
```

Or with a specific queue:

```bash
uv run python manage.py db_worker --queue-name "email"
```

### Testing the backends locally (worker + heartbeat in one process)

In production the `db_worker` and a per-minute heartbeat run alongside the web
server. Local dev has neither, so to confirm "is the queue actually draining?"
run the dev harness in a second terminal — it starts the worker **and** fires
the heartbeat on a loop, and reaps the worker on Ctrl-C:

```bash
make run                                   # window 1 — the dev server
make services                              # window 2 — worker + heartbeat
# Fast end-to-end check: enqueue one task and watch the worker drain it
make services ARGS="--interval 5 --smoke"
```

`--smoke` enqueues a `process_data_task`; you should see it reach `SUCCESSFUL`
(also visible at `/smallstack/explorer/` → System → Task results). The script is
`utils/dev_services.sh` (see `utils/README.md` for all flags). It does **not**
replace the production worker — that's wired into the container entrypoint below.

### Production (Docker Compose / Kamal)

By default, the web container runs `db_worker` inline — no separate worker service needed. The entrypoint script launches `db_worker` as a background process with a restart loop and cleans it up via a signal trap on container stop.

This is controlled by the `WORKER_INLINE` env var, which defaults to `true`.

### Separate Worker (Scaling Up)

For high-traffic sites or heavy background workloads, you can run the worker as a separate container for independent scaling and log separation.

**Docker Compose:** Set `WORKER_INLINE=false` on the web service and uncomment the `worker` service in `docker-compose.yml`:

```yaml
services:
  web:
    environment:
      - WORKER_INLINE=false
      # ... other env vars
  worker:
    build: .
    command: python manage.py db_worker --queue-name "*"
    # ...
```

**Kamal:** Add `WORKER_INLINE: "false"` to `env > clear` and uncomment the `worker` role in `deploy.yml`:

```yaml
env:
  clear:
    WORKER_INLINE: "false"
servers:
  web:
    - 123.45.67.89
  worker:
    hosts:
      - 123.45.67.89
    cmd: python manage.py db_worker --queue-name "*"
```

#### Trade-offs

| | Inline (default) | Separate Container |
|---|---|---|
| RAM per project | ~1x | ~2x (web + worker) |
| Worker crash recovery | Restart loop restarts process | Docker restarts container |
| Log separation | Mixed in one stream | Separate streams |
| Independent scaling | No | Yes |
| Deploy complexity | Single container | Worker role in deploy config |

#### When to switch to separate

- High-traffic sites where worker load could starve web requests
- Projects with heavy or long-running background tasks
- When you need independent scaling or monitoring

## Reliability: lost tasks and retries

`django-tasks-db` on its own has two gaps: a task whose worker is SIGKILLed /
OOM-killed / replaced mid-run stays `RUNNING` forever, and a task that raises is
simply `FAILED` — no retries. `apps/tasks/` closes both **without modifying the
engine**.

### Worker heartbeat + lost-task reaper

SmallStack ships its own `db_worker` command that **shadows** the upstream one
(`apps.tasks` precedes `django_tasks_db` in `INSTALLED_APPS`, and Django picks
the first app defining a command). Same arguments, same behaviour — plus:

1. On start it writes a `WorkerHeartbeat` row for a per-process **incarnation**
   id (`<--worker-id>#<token>`) and runs one **reaper pass**. That pass only
   catches a predecessor already past the staleness threshold, or one that
   exited cleanly — a worker restarted promptly after a crash leaves tasks too
   fresh to judge, and step 2 reaps them once the threshold elapses. It's a head
   start, not a guarantee the queue is clean before this worker claims anything.
2. A background thread refreshes the heartbeat every
   `SMALLSTACK_TASKS_HEARTBEAT_SECONDS` and reaps again every 4 beats (~1 min).
3. On exit (including a forced second SIGTERM) it marks the row stopped.

The reaper fails a `RUNNING` task as `apps.tasks.exceptions.WorkerLost` when the
worker that claimed it (`worker_ids[-1]`) has **stopped**, has **missed
heartbeats** for `SMALLSTACK_TASKS_LOST_AFTER_SECONDS`, or has **no heartbeat
row** and the task started over `SMALLSTACK_TASKS_ORPHAN_SECONDS` ago (a plain
upstream worker — conservative, since a long task looks the same). The update
is conditional on `status=RUNNING`, so a late finish wins and concurrent reapers
are safe. The traceback's last line says why: for the first two cases it names
the worker's host, pid and last-seen time; for the third there is no heartbeat
row to read those from, so it reports how long the task has been `RUNNING`
instead.

`last_seen_at` is written — and the staleness threshold evaluated — on the
**database** clock (`Now()`), not on any app server's `timezone.now()`. Two hosts
comparing wall clocks would make `LOST_AFTER_SECONDS` a measure of NTP skew, and
a worker whose clock ran slow would look permanently dead.

> "Heartbeat" here is the **worker** heartbeat (`apps/tasks`), not the uptime
> `heartbeat` command / `/status/` monitor (`apps/heartbeat`).

Nothing to deploy: every existing `db_worker` invocation (entrypoint, compose,
Kamal, `make services`) gets it. `manage.py reap_tasks [--dry-run]` runs a pass
by hand. `SMALLSTACK_TASKS_HEARTBEAT_ENABLED=False` makes `db_worker` a plain
pass-through — but the heartbeat thread is also the only thing that *runs* the
reaper, so disabling it leaves nothing reaping at all unless you schedule
`manage.py reap_tasks` yourself (cron, supercronic, or a `@scheduled` job).

**Dev gotcha:** under `DEBUG`, `db_worker` defaults to `--reload`, so the PID you
see is the autoreloader parent — killing it leaves the real worker (the child)
running. Test worker death with `--no-reload`.

### System checks

Everything above fails *silently* when misconfigured — the symptom is an absence
(no heartbeat, no reaper), which surfaces only when a worker dies. So
`manage.py check` reports three degraded configurations. All are warnings, and
none fires on shipped defaults:

| ID | Fires when | Why it matters |
|---|---|---|
| `tasks.W001` | another app's `db_worker` shadows ours (it precedes `apps.tasks` in `INSTALLED_APPS`) | workers run with no heartbeat; a dead worker's task waits out `ORPHAN_SECONDS` (a day) instead of 90s |
| `tasks.W002` | `LOST_AFTER_SECONDS` < 3 x `HEARTBEAT_SECONDS` | a live worker that misses a couple of beats has its running tasks failed and possibly re-run |
| `tasks.W003` | `HEARTBEAT_SECONDS` is not positive | not a usable beat interval |
| `tasks.W004` | `USE_TZ = False` | the reaper raises on every pass, and the failure is swallowed to keep workers alive — so it simply never reaps |
| `tasks.W005` | SmallStack could not disconnect Django's blanket finished-task ERROR logger | every failed attempt logs `ERROR` with a traceback, including ones being retried (see `logging-audit.md`) |

### Retries with backoff

Opt a task in with `@retry_policy`, applied **above** `@task` (like `@scheduled`):

```python
from django.tasks import task
from apps.tasks.reliability import retry_policy

@retry_policy(max_attempts=3, backoff=5, backoff_max=600, retry_on=(OSError,))
@task(queue_name="default")
def sync_invoice(invoice_id: int) -> None:
    ...
```

| Argument | Default | Meaning |
|---|---|---|
| `max_attempts` | `SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS` (1) | Attempts **including the first run** |
| `backoff` | `SMALLSTACK_TASKS_BACKOFF_SECONDS` (5) | **Upper bound** of the first delay, not the delay: equal jitter picks uniformly from `[bound/2, bound]`, so `5` waits 2.5–5s. Doubles per attempt |
| `backoff_max` | `SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS` (600) | Delay cap |
| `retry_on` | `(Exception,)` | Only these exception classes (and subclasses) retry |
| `retry_lost` | `True` | Also retry when the worker died (`WorkerLost`) or was force-stopped (`SystemExit`) |

How it works: when an attempt fails, a **fresh copy** of the task is enqueued
(same args, queue, priority, backend) with `run_after = now + delay`. Each
attempt is its own `DBTaskResult`, so **every traceback is kept**; a
`TaskAttempt` row links it to its chain (`root_id`, `parent_id`, `attempt`,
`cause`). Three paths can trigger a retry — the worker's `task_finished` signal
(normal), the reaper (lost tasks), and a **repair sweep** in every reaper pass
(a failure whose retry a crash skipped) — and the unique `parent_id` makes sure
only one wins.

**Rules that matter:**

- **Retries are opt-in.** Execution is at-least-once, so only tasks that are
  **safe to repeat** should retry. An undecorated task fails exactly as before.
- **A task can run twice — but not unnoticed.** Any worker paused past
  `LOST_AFTER_SECONDS` mid-task (a throttled container, a snapshotted VM, not
  just a network partition) is reaped and replaced, then resumes and writes its
  own result over the reaper's verdict. That late result *wins*: it is ground
  truth and the reaper is a heuristic. What SmallStack guarantees is that the
  disagreement is recorded, not just logged — `TaskAttempt.parent_completed_at`
  marks the chain (visible in Explorer → System → Task attempts),
  `chain_outcome().executed_more_than_once` reports it, the scheduler puts it in
  the run message, `ReapResult.reaped_then_completed` counts it separately from
  the benign `raced`, and it logs at WARNING. If the replacement hadn't started
  yet it is cancelled, and then the task really did run once.
- **The retry is a new task result.** A caller polling the *first* result id
  sees `FAILED`; to follow the chain use
  `chain_outcome(result_id)` → `.status` (`READY`/`RUNNING`/`SUCCESSFUL`/`FAILED`
  or `RETRYING`), `.row` (latest attempt), `.attempt`.
- **Per-enqueue budget:** `pin_max_attempts(result_id, n)` right after enqueueing
  overrides the policy for that chain (the scheduler uses this for
  `max_retries`); do it in the same transaction as the enqueue.
- **Retries need `DatabaseBackend`.** `ImmediateBackend` can't defer, and the
  retry receiver ignores its `task_finished`. Since django-tasks-db 0.13 every
  backend sends Django's own `django.tasks.signals`, so the receiver filters on
  `sender`. Tests on `ImmediateBackend` see the first failure only.
- **Each failed attempt logs at ERROR** to `django.tasks` (Django's own
  `log_task_finished` receiver, reached since django-tasks-db 0.13), even when
  a retry follows. Alert on the chain's outcome, not on those lines.
- **`context.attempt` is always 1** on this engine (each retry is a new result).
  Use `attempt_info(context.task_result.id).attempt` if a task body needs it.

### Testing reliability code

Switch the test to the real engine and drain with SmallStack's worker in-process:

```python
@pytest.fixture(autouse=True)
def _engine(settings):
    settings.TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend",
                                  "QUEUES": ["default", "email"]}}
    settings.SMALLSTACK_TASKS_BACKOFF_SECONDS = 0       # retries due immediately
    settings.SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS = 0

def _run_worker():
    with mock.patch.object(Worker, "configure_signals"):   # keep pytest's SIGINT
        call_command("db_worker", batch=True, startup_delay=False,
                     queue_name="*", worker_id="t", verbosity=0)
```

Use `pytest.mark.django_db(transaction=True)`, and define test tasks at **module
level** (the worker re-imports them by dotted path). See
`apps/tasks/test_retries.py` and `apps/tasks/test_reaper.py`.

## Built-in Tasks

SmallStack ships with these tasks in `apps/tasks/tasks.py`:

| Task | Queue | Description |
|------|-------|-------------|
| `send_email_task` | email | Send a plain-text email |
| `send_html_email_task` | email | Send an HTML email from a Django template |
| `send_welcome_email` | email | Send welcome email to new user (by user ID) |
| `process_data_task` | default | Example data processing task |
| `example_task_with_context` | default | Demonstrates `takes_context=True` |

The three email tasks carry `@retry_policy(max_attempts=3, backoff=30,
backoff_max=600, retry_on=(OSError,))` — SMTP and socket errors retry;
template/programming errors fail on the first attempt.

## Creating New Tasks

1. Add a function with `@task` decorator in any app's `tasks.py`
2. Import and call `.enqueue()` from views, signals, or management commands
3. Ensure the worker is running to process the queue

### Important Constraints

- **All arguments must be JSON-serializable** (no model instances — pass IDs instead).
  This includes nested values like an email task's `context` dict — a `datetime`
  or model instance in there breaks `.enqueue()` under the `DatabaseBackend`.
  **The test `ImmediateBackend` does *not* serialize args**, so a green unit test
  can still fail on the real queue — pass ISO strings / primitives, and test the
  enqueue path against `DatabaseBackend` when serialization matters.
- **Import models inside the function** to avoid circular imports
- **Tasks run in a separate process** — they don't share request context
- **HTML emails are auto-branded**: `send_html_email_task` merges brand context
  (`brand_name` / `brand_accent` / `site_url`) so templates extending
  `email/base_email.html` render their header even from a background task. Your
  `context` overrides these if you pass them.

## Test Configuration

The test settings must declare the same queues as production, or tasks with `queue_name="email"` will raise `InvalidTask`:

```python
# config/settings/test.py
TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
        "QUEUES": ["default", "email"],  # Must match production queues
    }
}
```

The `ImmediateBackend` executes tasks synchronously — no worker needed during tests — but still validates queue names against the allowed list.

## Task Visibility

### Django Admin

Task results are visible in the Django admin under "Django Tasks Database". You can see:
- Task status (pending, running, successful, failed)
- Arguments passed
- Result or error message
- Timing information

### Explorer

Task results are also registered in Explorer under the **System** group, providing staff users a read-only view of recent task activity without needing Django admin access. Visit Explorer → System → DB Task Results. The same group has **Worker heartbeats** (which workers are alive, and when each was last seen or stopped) and **Task attempts** (retry chains: attempt number, cause, parent/root ids).

## Best Practices

1. **Pass IDs, not objects** — Fetch models inside the task function
2. **Use named queues** — Separate email tasks from data processing
3. **Keep tasks idempotent** — required before adding `@retry_policy`, and wise anyway: a reaped task may have partly run
4. **Log inside tasks** — Use `logging.getLogger(__name__)` for visibility
5. **Test tasks synchronously** — Call the function directly in tests (skip `.enqueue()`)
