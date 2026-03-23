# Skill: Background Tasks

This skill describes how to create and run background tasks in SmallStack using Django's built-in Tasks framework with the `django-tasks-db` backend.

## Overview

SmallStack uses Django 6's native `django.tasks` framework with the `django-tasks-db` database backend. Tasks are stored in the database and processed by a separate worker process. No Redis or Celery required.

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

### Production (Docker Compose)

The `worker` service in `docker-compose.yml` runs automatically:

```yaml
worker:
  build: .
  command: python manage.py db_worker --queue-name "*"
  volumes:
    - db_data:/data
  depends_on:
    web:
      condition: service_healthy
```

### Production (Kamal)

Kamal deploys the worker as an accessory or secondary container. See `kamal-deployment.md`.

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
