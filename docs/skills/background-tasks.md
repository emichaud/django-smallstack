# Skill: Background Tasks

This skill describes how to create and run background tasks in SmallStack using Django's built-in Tasks framework with the `django-tasks-db` backend.

## Overview

SmallStack uses Django 6's native `django.tasks` framework with the `django-tasks-db` database backend. Tasks are stored in the database and processed by a separate worker process. No Redis or Celery required.

> **Coming soon: recurring scheduling.** Today the queue is *one-shot* — you `.enqueue()` a task and a worker runs it once. A recurring `@scheduled(every="5m")` primitive (retries with backoff, dead-letter handling) is **coming soon**. Until it lands, run recurring jobs as management commands wired to system cron — e.g. `rebuild_search_index`, `heartbeat`, `prune_activity`.

## File Locations

```
apps/tasks/
├── tasks.py        # Task definitions
├── apps.py         # App config

config/settings/base.py   # TASKS configuration
docker-compose.yml         # Worker service definition
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

## Built-in Tasks

SmallStack ships with these tasks in `apps/tasks/tasks.py`:

| Task | Queue | Description |
|------|-------|-------------|
| `send_email_task` | email | Send a plain-text email |
| `send_html_email_task` | email | Send an HTML email from a Django template |
| `send_welcome_email` | email | Send welcome email to new user (by user ID) |
| `process_data_task` | default | Example data processing task |
| `example_task_with_context` | default | Demonstrates `takes_context=True` |

## Creating New Tasks

1. Add a function with `@task` decorator in any app's `tasks.py`
2. Import and call `.enqueue()` from views, signals, or management commands
3. Ensure the worker is running to process the queue

### Important Constraints

- **All arguments must be JSON-serializable** (no model instances — pass IDs instead)
- **Import models inside the function** to avoid circular imports
- **Tasks run in a separate process** — they don't share request context

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

Task results are also registered in Explorer under the **System** group, providing staff users a read-only view of recent task activity without needing Django admin access. Visit Explorer → System → DB Task Results.

## Best Practices

1. **Pass IDs, not objects** — Fetch models inside the task function
2. **Use named queues** — Separate email tasks from data processing
3. **Keep tasks idempotent** — They may be retried on failure
4. **Log inside tasks** — Use `logging.getLogger(__name__)` for visibility
5. **Test tasks synchronously** — Call the function directly in tests (skip `.enqueue()`)
