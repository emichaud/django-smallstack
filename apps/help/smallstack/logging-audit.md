---
title: Logging & Audit Trail
description: Built-in logging and activity tracking that just works
---

# Logging & Audit Trail

Python's logging module is powerful but notoriously fiddly to configure. Django adds its own layer of loggers, handlers, and formatters on top — and most tutorials either skip it entirely or dump a wall of configuration without explaining what it does.

{{ project_name }} takes a different approach: **sensible defaults that just work**, using the same proven patterns Django admin already uses internally. You get structured logging in dev and production, plus a built-in audit trail — no extra packages required.

## What's Already Set Up

When you run `make run`, logging is already working:

- **Your app code** (`apps.*`) logs at DEBUG in dev, INFO in production
- **Django request errors** (4xx, 5xx) show up in your dev console automatically
- **Security events** are captured at INFO in dev, WARNING in production
- **Production logs** output as JSON with timestamps and logger names — ready for any log aggregation tool

You don't need to configure anything. Just start logging.

## How to Add Logging to Your Code

### Step 1: Add a logger at the top of your file

```python
# apps/tickets/views.py
import logging

logger = logging.getLogger(__name__)
```

That's it for setup. The `__name__` pattern gives your logger a name like `apps.tickets.views`, which the `apps` catch-all logger in settings already captures. This is the same pattern Django uses throughout its own codebase.

### Step 2: Log events where they matter

```python
def close_ticket(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    ticket.status = "closed"
    ticket.save()
    logger.info("Ticket %s closed by %s", ticket.pk, request.user.username)
```

In development, you'll see this in your terminal:

```
2026-03-04 14:23:01,123 INFO apps.tickets.views Ticket 42 closed by admin
```

In production, the same event outputs as JSON:

```json
{"time": "2026-03-04 14:23:01", "level": "INFO", "name": "apps.tickets.views", "module": "views", "message": "Ticket 42 closed by admin"}
```

### Step 3: Pick the right level

| Level | When to use it | Dev | Prod |
|-------|---------------|-----|------|
| `logger.debug()` | Verbose details while developing | Shows | Hidden |
| `logger.info()` | Notable events (user actions, completions) | Shows | Shows |
| `logger.warning()` | Unexpected but not broken | Shows | Shows |
| `logger.error()` | Something failed | Shows | Shows |

**Rule of thumb:** Use `debug()` for "I'm investigating something right now" and `info()` for "I'd want to know about this in production."

## A Complete Example

Here's a view with logging done well — not too much, not too little:

```python
# apps/tickets/views.py
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import UpdateView

from apps.smallstack.audit import AuditMixin
from .models import Ticket

logger = logging.getLogger(__name__)


class TicketCloseView(AuditMixin, LoginRequiredMixin, UpdateView):
    model = Ticket
    fields = ["status", "resolution_note"]

    def form_valid(self, form):
        logger.info(
            "Ticket %s closed by %s",
            self.object.pk,
            self.request.user.username,
        )
        return super().form_valid(form)
```

This gives you:
- **Text logging** — the `logger.info()` line prints to your console/stdout
- **Audit trail** — the `AuditMixin` creates a permanent database record of who changed what

## Audit Trail with LogEntry

Django admin already tracks every add, change, and delete action using a built-in model called `LogEntry`. {{ project_name }} lets you use that same system from your own views — no extra models, no migrations, no packages.

### Quick audit with log_action()

```python
from apps.smallstack.audit import log_action, CHANGE

def approve_request(request, pk):
    req = get_object_or_404(AccessRequest, pk=pk)
    req.status = "approved"
    req.save()
    log_action(request.user, req, CHANGE, "Approved access request")
    return redirect("requests:list")
```

This creates a record in Django's `LogEntry` table — the exact same place admin actions are stored. You can browse all activity at `/admin/admin/logentry/` with filters for user, action type, and content type.

### Available action flags

| Flag | Import | When to use |
|------|--------|-------------|
| `ADDITION` | `from apps.smallstack.audit import ADDITION` | Object was created |
| `CHANGE` | `from apps.smallstack.audit import CHANGE` | Object was modified |
| `DELETION` | `from apps.smallstack.audit import DELETION` | Object was deleted |

### Automatic audit with AuditMixin

For `CreateView` and `UpdateView`, `AuditMixin` handles it automatically:

```python
from apps.smallstack.audit import AuditMixin

class DocumentCreateView(AuditMixin, LoginRequiredMixin, CreateView):
    model = Document
    fields = ["title", "content"]

class DocumentUpdateView(AuditMixin, LoginRequiredMixin, UpdateView):
    model = Document
    fields = ["title", "content", "status"]
```

The mixin detects whether it's a create or update, and logs which fields changed (e.g., "Changed title, status."). To customize the message:

```python
class DocumentUpdateView(AuditMixin, LoginRequiredMixin, UpdateView):
    model = Document
    fields = ["title", "status"]

    def get_audit_message(self, form):
        if "status" in form.changed_data:
            return f"Status changed to {form.instance.get_status_display()}"
        return super().get_audit_message(form)
```

## Browsing the Activity Log

LogEntry is registered in Django admin as a read-only activity log. Visit `/admin/admin/logentry/` to see all actions — both from admin and from your `log_action()` calls. You can filter by action type, content type, and user, and search by object name or change message.

## Logging vs Audit: When to Use Which

| | Text Logging (`logger.*`) | Audit (`log_action()`) |
|---|---|---|
| **Where it goes** | Console / stdout | Database (LogEntry table) |
| **Persists** | Only if you collect logs | Always — queryable in admin |
| **Best for** | Debugging, monitoring, operations | "Who did what to which record" |
| **Performance** | Very fast (just a print) | Database write per call |
| **Use it for** | Errors, warnings, flow tracing | User actions on business objects |

Most views need just `logger.info()`. Add `log_action()` when you need to answer "who changed this and when?" — things like approvals, status changes, or deletions.

## Adjusting Log Levels

### Quiet a noisy app in development

```python
# config/settings/development.py
LOGGING["loggers"]["apps.noisy_app"] = {
    "handlers": ["console"],
    "level": "WARNING",
    "propagate": False,
}
```

### Enable SQL query logging

Uncomment the `django.db.backends` DEBUG logger in `config/settings/development.py`:

```python
"django.db.backends": {
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
},
```

This is very verbose — every SQL query will print to your console. Useful for debugging N+1 queries.

## Logging to a File

By default, all logs go to the console (stdout) — which is the right choice for Docker containers and most cloud platforms, where a log collector picks up stdout automatically.

But if you're running on a VPS or want a persistent log file you can `tail -f` or review later, set the `LOG_FILE` environment variable in production:

```bash
# In .env or .kamal/secrets
LOG_FILE=/app/data/logs/app.log
```

That's it. When `LOG_FILE` is set, {{ project_name }} adds a `RotatingFileHandler` to every logger — so all log output goes to both the console **and** the file. The defaults are reasonable:

| Setting | Default | What it means |
|---------|---------|---------------|
| Max file size | 5 MB | Rotates to a new file after 5 MB |
| Backup count | 5 | Keeps `app.log`, `app.log.1` through `app.log.5` |
| Format | JSON | Same JSON format as console output |
| Max disk usage | ~30 MB | 6 files x 5 MB (current + 5 backups) |

### Important: create the directory first

Django won't create the log directory for you. Make sure it exists before starting the app:

```bash
# On your VPS or in your Dockerfile
mkdir -p /app/data/logs
```

For Docker deployments, add the logs directory to your data volume so logs persist across container rebuilds:

```yaml
# docker-compose.yml
volumes:
  - db_data:/app/data  # Already covers /app/data/logs/
```

### When NOT to use file logging

- **Docker / containers** — Use stdout (the default). Your container platform collects it.
- **Heroku / PaaS** — These capture stdout. File writes may not persist.
- **If you have a log aggregation service** — Services like Datadog or CloudWatch read from stdout.

File logging is most useful on a **bare VPS or dedicated server** where you SSH in and want to `tail -f /app/data/logs/app.log` to see what's happening.

### Development

File logging is intentionally not wired up in development — your terminal is right there. If you want it for a specific debugging session, add it temporarily to `development.py`:

```python
# Temporary file logging for debugging (remove when done)
LOGGING["handlers"]["file"] = {
    "class": "logging.handlers.RotatingFileHandler",
    "filename": BASE_DIR / "debug.log",
    "maxBytes": 5 * 1024 * 1024,
    "backupCount": 1,
    "formatter": "verbose",
}
LOGGING["loggers"]["apps"]["handlers"].append("file")
```

## Log Levels by Environment

| Logger | Development | Production |
|--------|-------------|------------|
| `django` | INFO | WARNING |
| `django.request` | DEBUG | ERROR |
| `django.db.backends` | WARNING | — |
| `django.security` | INFO | WARNING |
| `apps` (your code) | DEBUG | INFO |

## When You're Ready: External Log Services

{{ project_name }} doesn't bundle any external logging integrations — but it's already set up so they work the moment you need them. The JSON-formatted production output with timestamps and logger names is exactly what these tools expect. You don't need to rework your logging config when the time comes.

### Log collectors (Grafana/Loki, Graylog, Datadog, CloudWatch)

These tools work **outside** your Django process. They read your logs from stdout or from files — you don't install anything in Python or change your settings. You configure the collector at the infrastructure level, point it at your container's stdout or your `LOG_FILE` path, and it picks up the JSON lines automatically.

That's the whole point of the JSON formatter in production. A line like:

```json
{"time": "2026-03-04 14:23:01", "level": "INFO", "name": "apps.tickets.views", "module": "views", "message": "Ticket 42 closed by admin"}
```

is already structured data that any collector can parse, index, and search. There's nothing to change in Django.

### Sentry (error tracking)

Sentry is different — it's the one tool that actually hooks into your Python process. It captures exceptions with full tracebacks, request context, and user info. It also patches Python's logging module, so your existing `logger.error()` calls automatically flow to Sentry without changing any of your code.

Setup is minimal:

```bash
uv add sentry-sdk
```

```python
# config/settings/production.py
import sentry_sdk

sentry_sdk.init(
    dsn=config("SENTRY_DSN", default=""),
    traces_sample_rate=0.1,
)
```

That's it. Your existing `logger.error()` and `logger.warning()` calls, plus any unhandled exceptions, will appear in Sentry's dashboard. Everything you've already instrumented with `logger.*` just works — Sentry reads from the same logging system.

### What connects where

| Tool | How it reads your logs | Django changes needed |
|------|----------------------|----------------------|
| Grafana / Loki | Collects stdout or log files | None — JSON output already works |
| Graylog | Collects stdout or log files | None |
| Datadog / CloudWatch | Reads stdout from containers | None |
| Sentry | Python SDK, hooks into logging | `sentry-sdk` package + 3 lines in settings |

### The bottom line

You don't need any of these tools to start. `logger.info()` to your console is a perfectly good logging strategy for a project that's getting off the ground. But when your project grows to the point where you want centralized log search, alerting, or error tracking, {{ project_name }}'s logging is already in the right shape. You add the external tool — not rework your application.

## AI Skill File

A corresponding skill file at `docs/skills/logging-audit.md` helps AI coding assistants include proper logging when generating new features or fixes. When an AI agent creates a new view, it can follow the `getLogger(__name__)` pattern and use `AuditMixin` or `log_action()` where appropriate — producing code that's consistent with the rest of your project from the start.

## Why This Matters

Logging is one of those things that seems simple but trips up developers — especially less experienced ones — more than it should. Python's logging module has layers of loggers, handlers, formatters, and propagation rules that interact in non-obvious ways. Most Django starters either ignore it or include a copy-pasted config nobody understands.

{{ project_name }} follows the same philosophy here as everywhere else: **use Django's built-in, proven patterns** and configure them sensibly so they work out of the box. The `LogEntry` model has been in Django since the beginning. The `getLogger(__name__)` pattern is standard Python. Nothing here is custom or clever — it's just wired up properly so you can focus on your application instead of fighting configuration.

That same principle applies to where your logs go. Console logging in dev, JSON to stdout in production, optional file logging with one env var, and a clear path to Grafana or Sentry when you outgrow that. Each step builds on the last — no rip-and-replace.
