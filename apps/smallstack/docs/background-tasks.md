---
title: Background Tasks
description: Running tasks outside the request-response cycle
---

# Background Tasks

> **Building this?** Read the agent-facing skill first: [`docs/skills/background-tasks.md`](../../../docs/skills/background-tasks.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

Django 6.0 introduced a built-in **Tasks framework** for running code outside the HTTP request-response cycle. This enables offloading work like sending emails, processing data, or generating reports to background workers, keeping your web responses fast.

## Why Use Background Tasks?

Without background tasks, long-running operations block web requests:

```python
# Bad: User waits while email sends
def signup_view(request):
    user = create_user(request.POST)
    send_welcome_email(user)  # Blocks for 2-5 seconds
    return redirect("home")   # User finally sees response
```

With background tasks, the response is immediate:

```python
# Good: Email sends in background
from apps.tasks.tasks import send_welcome_email

def signup_view(request):
    user = create_user(request.POST)
    send_welcome_email.enqueue(user_id=user.id)  # Returns instantly
    return redirect("home")  # User sees response immediately
```

## How It Works

1. **Define a task** using the `@task` decorator
2. **Enqueue the task** with `.enqueue()` when needed
3. **Worker processes** pick up and execute queued tasks
4. **Results** are stored in the database for later retrieval

## Running the Worker

{{ project_name }} uses the **DatabaseBackend** which stores tasks in SQLite/PostgreSQL. To process tasks, run the worker:

```bash
# Start the background worker, on every queue (default, email, webhooks)
uv run python manage.py db_worker --queue-name "*"
```

A bare `db_worker` takes only the `default` queue: invites and sign-in codes
(`email`) and webhook deliveries (`webhooks`) would wait for a worker that never comes.

In development (DEBUG=True), the worker auto-reloads when code changes. Keep it running in a separate terminal while developing.

In production, the worker runs automatically inside the web container — no extra setup needed. For high-traffic sites that need independent scaling, you can run the worker as a separate container by setting `WORKER_INLINE=false`. See [Docker Deployment](/smallstack/help/smallstack/docker-deployment/) for details.

## Defining Tasks

Create tasks in a `tasks.py` file. Tasks must be module-level functions:

```python
# apps/myapp/tasks.py
from django.tasks import task
from django.core.mail import send_mail

@task
def send_notification_email(user_email, message):
    """Send a notification email in the background."""
    return send_mail(
        subject="Notification",
        message=message,
        from_email=None,
        recipient_list=[user_email],
    )
```

### Task Parameters

The `@task` decorator accepts several options:

```python
@task(
    priority=5,           # Higher priority = processed first (default: 0)
    queue_name="email",   # Separate queues for different task types
    backend="default",    # Which backend to use
    takes_context=True,   # Receive TaskContext as first argument
)
def my_task(context, data):
    print(f"Task {context.task_result.id}, attempt {context.attempt}")
    return process(data)
```

## Enqueueing Tasks

Call `.enqueue()` to add a task to the queue:

```python
from apps.tasks.tasks import send_email_task

# Enqueue with arguments
result = send_email_task.enqueue(
    recipient="user@example.com",
    subject="Hello",
    message="This is your message."
)

# The result object contains the task ID
print(f"Task queued: {result.id}")
```

### From async code

SmallStack serves requests over WSGI and ships no async views, so `enqueue()`
above is the call to use everywhere in a stock project: views, signals,
management commands, MCP tools.

Django also provides `aenqueue()`, the awaitable form, for code that is
already running inside an event loop, such as an async view you add under ASGI.
Calling the plain `enqueue()` there raises `SynchronousOnlyOperation`, because
the database backend writes a row.

```python
async def my_async_view(request):
    result = await send_email_task.aenqueue(
        recipient="user@example.com",
        subject="Hello",
        message="Queued from async code.",
    )
```

## Checking Task Status

Retrieve and check task results:

```python
from apps.tasks.tasks import process_data_task

# Enqueue the task
result = process_data_task.enqueue(data={"items": [1, 2, 3]})
task_id = result.id

# Later, check status
result = process_data_task.get_result(task_id)
result.refresh()  # Update from database

print(result.status)  # PENDING, RUNNING, SUCCESSFUL, or FAILED

if result.status == "SUCCESSFUL":
    print(result.return_value)  # The task's return value
```

### Task Statuses

| Status | Meaning |
|--------|---------|
| `READY` | Task is queued, waiting for a worker |
| `RUNNING` | Worker is currently executing the task |
| `SUCCESSFUL` | Task completed without errors |
| `FAILED` | Task raised an exception |

## Built-in Example Tasks

{{ project_name }} includes example tasks in `apps/tasks/tasks.py`:

### send_email_task

Send emails in the background:

```python
from apps.tasks.tasks import send_email_task

result = send_email_task.enqueue(
    recipient="user@example.com",
    subject="Important Update",
    message="Here's your update content."
)
```

### send_welcome_email

Send a welcome email to a user by ID:

```python
from apps.tasks.tasks import send_welcome_email

# After creating a user
send_welcome_email.enqueue(user_id=user.id)
```

### process_data_task

Example of data processing in background:

```python
from apps.tasks.tasks import process_data_task

result = process_data_task.enqueue(
    data={"items": [1, 2, 3, 4, 5]},
    operation="transform"
)
```

## Transaction Safety

When enqueueing tasks inside database transactions, use `on_commit` to prevent race conditions:

```python
from functools import partial
from django.db import transaction

with transaction.atomic():
    order = Order.objects.create(...)
    # Task won't be enqueued if transaction rolls back
    transaction.on_commit(
        partial(send_order_confirmation.enqueue, order_id=order.id)
    )
```

## Serialization Requirements

Task arguments and return values must be **JSON-serializable**:

```python
# These work
send_email.enqueue(email="test@example.com")  # strings
process.enqueue(count=42)                      # numbers
analyze.enqueue(items=[1, 2, 3])              # lists
transform.enqueue(data={"key": "value"})      # dicts

# These don't work
process.enqueue(date=datetime.now())          # datetime objects
process.enqueue(user=user_instance)           # model instances
process.enqueue(data={(1, 2): "value"})       # tuple keys
```

For model instances, pass the ID instead:

```python
# Instead of: send_welcome_email.enqueue(user=user)
send_welcome_email.enqueue(user_id=user.id)
```

## When Workers Die: Lost Tasks and Retries

A worker process can die mid-task: a deploy replaces the container, the machine
runs out of memory, someone runs `kill -9`. On its own, the task engine would
leave that task marked **Running** forever. SmallStack's `db_worker` prevents that:

- Every worker records a **worker heartbeat** every 15 seconds (not the same
  thing as the uptime heartbeat on the status page).
- About once a minute (every 4 heartbeats), and whenever a worker starts, workers
  check for tasks whose worker has stopped or gone quiet for 90 seconds. Those
  tasks are marked **Failed** with the error `WorkerLost` and a message saying
  which worker died and when it was last seen. If you change the 15-second
  heartbeat interval, the once-a-minute check moves with it.

You don't need to set anything up. The `db_worker` you already run does this.

### When a task runs twice

Occasionally a worker isn't really dead — just frozen long enough to look it (a
container starved of CPU, a virtual machine paused and resumed). SmallStack
declares its task lost and runs it again; then the original worker wakes up and
finishes too. The task has now run twice.

The result the original worker reports is kept, because it actually happened.
What SmallStack promises is that this is never hidden from you:

- the run says so — "ran more than once: attempt 1 completed after being declared lost";
- a warning is logged naming the task;
- it's recorded permanently under **Explorer → System → Task attempts**, in the
  *Parent completed at* column.

If the second run hadn't started yet, it's cancelled and the task ran only once.
Tasks that must never repeat — charging a card, shipping an order — should be
written so that running them twice is harmless.

### Retrying failed tasks

A task can ask to be retried when it fails. Put `@retry_policy` above `@task`:

```python
from django.tasks import task
from apps.tasks.reliability import retry_policy

@retry_policy(max_attempts=3, retry_on=(OSError,))
@task
def sync_invoice(invoice_id):
    ...
```

A failed attempt is then queued again after a delay that grows each time —
up to 5s, then up to 10s, then up to 20s, never more than 10 minutes. The
setting is the *longest* each wait can be: the actual wait is picked at random
between half of it and all of it (so a 5s setting waits 2.5–5s), which stops a
batch of tasks that failed together from retrying together. Each attempt keeps
its own record and
error, so you can see the whole history. The built-in email tasks already retry
up to 3 times on connection and SMTP errors.

**Only retry tasks that are safe to run twice.** A retried task may repeat work
that partly happened the first time, so retries are off unless a task asks for
them. Scheduled jobs have their own **Retries on failure** setting (see the
[Scheduler](/smallstack/help/smallstack/scheduler/) page).

### Settings

| Setting | Default | What it controls |
|---|---|---|
| `SMALLSTACK_TASKS_HEARTBEAT_ENABLED` | `True` | Turn the worker heartbeat and lost-task checks off |
| `SMALLSTACK_TASKS_HEARTBEAT_SECONDS` | `15` | How often each worker checks in |
| `SMALLSTACK_TASKS_LOST_AFTER_SECONDS` | `90` | How long a worker can be silent before its tasks are failed |
| `SMALLSTACK_TASKS_ORPHAN_SECONDS` | `86400` | Same, for workers that never sent a heartbeat |
| `SMALLSTACK_TASKS_DEFAULT_MAX_ATTEMPTS` | `1` | Attempts for tasks with no retry policy (1 = no retries) |
| `SMALLSTACK_TASKS_BACKOFF_SECONDS` | `5` | Longest the first retry waits (actual wait is 2.5–5s) |
| `SMALLSTACK_TASKS_BACKOFF_MAX_SECONDS` | `600` | Longest retry delay |

Staff can see workers and retry chains in **Explorer → System → Worker
heartbeats** and **Task attempts**.

## Task Maintenance

Clean up old completed tasks periodically:

```bash
# Delete tasks older than 7 days
uv run python manage.py prune_db_task_results --age 7

# See all options
uv run python manage.py prune_db_task_results --help
```

## Configuration

Task settings are in `config/settings/base.py`:

```python
TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default", "email"],
    }
}
```

### Multiple Queues

Separate queues allow different workers to handle different task types:

```bash
# Worker for all queues (recommended)
uv run python manage.py db_worker --queue-name "*"

# Worker for specific queues (comma-separated): name every queue some worker must drain
uv run python manage.py db_worker --queue-name "default,email,webhooks"

# Worker for the default queue only (email and webhooks then need workers of their own)
uv run python manage.py db_worker
```

### Development Without Worker

For simple development, you can run tasks immediately (synchronously):

```python
# config/settings/development.py
TASKS = {
    "default": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
    }
}
```

This blocks the request until the task completes, so it's only for testing.

## Alternative: Celery

{{ project_name }} uses Django's built-in task framework with `django-tasks-db` for simplicity. This provides:

- No external dependencies (uses your existing database)
- Simple setup and configuration
- Automatic worker reload in development
- Good enough for most small-to-medium applications

For **recurring work** — cron expressions, intervals, run-once-at-a-time — you don't need Celery: {{ project_name }} ships a full [scheduler](/smallstack/help/smallstack/scheduler/) on top of this task engine (`@scheduled` decorator, themed control console at `/smallstack/scheduler/`, run history, overlap and catch-up policies).

For **high-volume production** systems, consider [Celery](https://docs.celeryq.dev/):

| Feature | Django Tasks + SmallStack scheduler | Celery |
|---------|-------------|--------|
| Setup complexity | Simple | Moderate |
| External dependencies | None | Redis/RabbitMQ |
| Scheduling | Cron / interval / once (`@scheduled`, DST-aware) | Advanced (celery beat) |
| Retries | Manual (webhooks add their own backoff tick) | Built-in with backoff |
| Monitoring | Scheduler console + status monitors | Flower dashboard |
| Scaling | Limited | Distributed workers |
| Best for | Small-to-medium apps | High-volume systems |

To use Celery instead:

1. Install: `uv add celery redis`
2. Configure a message broker (Redis recommended)
3. Create `celery.py` in your config directory
4. Define tasks with `@shared_task` decorator
5. Run: `celery -A config worker -l INFO`

See the [Celery documentation](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html) for detailed setup.

## Production Deployment

In production (Docker Compose or Kamal), the background worker runs **inline inside the web container** by default. No separate worker service or configuration is needed — the entrypoint script starts `db_worker` as a background process automatically.

This is controlled by the `WORKER_INLINE` environment variable, which defaults to `true`.

### Scaling Up: Separate Worker Container

For high-traffic sites or heavy background workloads, you can split the worker into a separate container. This gives you independent scaling, separate log streams, and Docker-managed crash recovery.

Set `WORKER_INLINE=false` on the web service and uncomment the `worker` service/role in your deployment config:

**Docker Compose:**

```yaml
services:
  web:
    environment:
      - WORKER_INLINE=false

  worker:
    build: .
    command: python manage.py db_worker --queue-name "*"
    volumes:
      - db_data:/data
    depends_on:
      web:
        condition: service_healthy
```

**Kamal:**

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

### Inline vs Separate: Trade-offs

| | Inline (default) | Separate Container |
|---|---|---|
| RAM per project | ~1x | ~2x (web + worker) |
| Worker crash recovery | Restart loop restarts process | Docker restarts container |
| Log separation | Mixed in one stream | Separate streams |
| Independent scaling | No | Yes |
| Deploy complexity | Single container | Worker role in deploy config |

**Use inline** for most sites — marketing pages, internal tools, apps with occasional background tasks.

**Switch to separate** when worker load could starve web requests, you have heavy/long-running tasks, or you need independent scaling or monitoring.

> **See also:** [Docker Deployment](/smallstack/help/smallstack/docker-deployment/) and [Kamal Deployment](/smallstack/help/smallstack/kamal-deployment/) for full deployment documentation.

## Troubleshooting

### Tasks not running

1. Is the worker running? Check with `ps aux | grep db_worker`
2. Are there pending tasks? Check in Django admin or database
3. Is the correct settings module loaded?

### Tasks failing silently

Check task results for errors:

```python
result = my_task.get_result(task_id)
if result.status == "FAILED":
    for error in result.errors:
        print(f"Exception: {error.exception_class}")
        print(error.traceback)
```

### A task has been "Running" for a long time

If its worker died, the task is marked **Failed** (`WorkerLost`) within about
a few minutes, as long as some worker is running. If it's still Running, its worker is alive and
the task itself is slow or stuck. Check **Explorer → System → Worker
heartbeats** to see which is the case. To check now instead of waiting:

```bash
uv run python manage.py reap_tasks --dry-run   # show what would be failed
uv run python manage.py reap_tasks             # fail them (and retry if allowed)
```

### Worker not picking up code changes

In development, the worker should auto-reload. If not:

1. Check DEBUG is True
2. Restart the worker manually
3. Ensure `--reload` flag is used

## Further Reading

- [Django Tasks Documentation](https://docs.djangoproject.com/en/6.0/topics/tasks/)
- [django-tasks-db GitHub](https://github.com/RealOrangeOne/django-tasks-db)
- [Celery Documentation](https://docs.celeryq.dev/)
