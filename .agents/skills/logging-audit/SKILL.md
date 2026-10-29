---
name: logging-audit
description: "Logging configuration, audit trail, and reading logs from a deployment you can't shell into — JSON output with request_id correlation, DB-backed capture, the /smallstack/logs/ staff viewer, time-boxed capture windows"
license: MIT
metadata:
  source: "docs/skills/logging-audit.md"
  section: "Available Skills"
  generated-by: "smallstack-skills-index"
---

> Generated from `docs/skills/logging-audit.md` by `make skills-index` — edit the source, not this file.

# Logging & Audit

SmallStack includes sensible logging defaults and a lightweight audit utility built on Django's `LogEntry` model.

## Logging

### Adding logging to an app

Use Python's stdlib logger with `__name__` so log output automatically includes the module path:

```python
# apps/tickets/views.py
import logging

logger = logging.getLogger(__name__)

def close_ticket(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    ticket.status = "closed"
    ticket.save()
    logger.info("Ticket %s closed by %s", ticket.pk, request.user)
```

All `apps.*` loggers are captured by the `apps` logger configured in settings.

### Attaching structured fields

Pass `extra={...}` for anything you'd want to filter or group on later. These land in the `extra` object of the production JSON output — don't concatenate them into the message string:

```python
logger.warning("Blocked probe", extra={"user_agent": ua, "score": score})
```

```json
{"time": "…", "level": "WARNING", …, "extra": {"user_agent": "curl/8.1", "score": 0.93}}
```

Keys must not collide with `LogRecord` built-ins (`name`, `module`, `message`, `args`, `levelname`, …) — Python raises `KeyError` at the call site if they do.

### Request IDs for correlation

Every request gets a unique `X-Request-ID` via `RequestIDMiddleware` (first in the middleware stack). Access it as `request.id` in views and middleware. The ID is:

- returned in the `X-Request-ID` response header,
- stored in `RequestLog.request_id`,
- and injected into **every log line emitted while handling that request**, as the `request_id` field.

So "user reported an error, here's their request ID" is a one-search answer across both the log stream and the activity log. You don't pass it anywhere — `RequestContextFilter` reads it from a `contextvar` that the middleware binds.

### Trace IDs for multi-step work

For work that spans many log lines and isn't a single HTTP request — a scheduled job, a webhook delivery chain, an agent run — bind a trace ID and every line emitted inside it carries `trace_id`:

```python
import uuid

from apps.smallstack.logging import bind_trace_id, reset_trace_id

token = bind_trace_id(f"trace_{uuid.uuid4().hex}")
try:
    run_the_multi_step_thing()   # every logger.* call in here is tagged
finally:
    reset_trace_id(token)
```

Always reset in a `finally` — worker threads are reused, and an unreset value would tag unrelated later work.

**`apps.tasks` and `apps.scheduler` already do this for you.** Every background task gets a `trace_task_<id>` bound around its execution automatically (`apps/tasks/tracing.py`, hooked into the task-running signals every task funnels through, regardless of which app enqueued it), and the scheduler's own tick binds a `trace_schedjob_<job pk>_<tick>` around each job's tick-time processing. Reach for `bind_trace_id()` yourself for work these two don't cover — a webhook delivery chain, a multi-step pipeline outside the task/scheduler system.

### Log levels by environment

| Logger | Development | Production |
|--------|-------------|------------|
| `django` | INFO | WARNING |
| `django.request` | DEBUG (see 4xx/5xx) | ERROR |
| `django.db.backends` | WARNING | — |
| `django.security` | INFO | WARNING |
| `apps` (your code) | DEBUG | INFO |

### Enabling SQL query logging in development

Uncomment the `django.db.backends` DEBUG logger in `config/settings/development.py`:

```python
"django.db.backends": {
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
},
```

### Adjusting log levels

Override any logger in your project's settings:

```python
# In development.py or production.py
LOGGING["loggers"]["apps.tickets"] = {
    "handlers": ["console"],
    "level": "WARNING",  # Quiet a noisy app
    "propagate": False,
}
```

### `django.tasks` — SmallStack replaces one of Django's own receivers

Worth knowing before you touch task signals or alert on this logger.

Django ships a `log_task_finished` receiver that logs **every** `FAILED` task
result at `ERROR` with a traceback. SmallStack retries tasks
(`docs/skills/background-tasks.md`), so an attempt that is about to be retried
would raise an `ERROR` for a failure the queue then absorbs — a page for a
non-event, and the feature's success becomes its own false-alarm source.

So `apps/tasks/signals.py` **disconnects Django's receiver** and connects its
own:

| Outcome | Level | Record |
|---|---|---|
| Failed, retry enqueued | `WARNING` | `Task id=… path=… state=FAILED retrying_as=<id>`, no traceback |
| Failed, final | `ERROR` | identical to Django's, traceback included |
| Succeeded | `INFO` | identical to Django's |

Same `django.tasks` logger and same `Task id=… path=… state=…` prefix, so
existing alert rules and log parsers keep matching — only the severity of an
absorbed failure changes. `SMALLSTACK_TASKS_SOFTEN_RETRYABLE_LOGS=False`
restores Django's stock behaviour.

Two things to keep in mind:

- **It is order-dependent.** Django registers its receiver when
  `django.tasks.signals` is imported, so it would otherwise run *before*
  SmallStack's retry receiver has decided anything — which is why this is a
  takeover rather than a logging filter. A filter could only have suppressed the
  record, not corrected it, and suppressing is worse for an audit trail.
  SmallStack's logger is connected *after* its retry receiver on purpose.
- **If the takeover ever fails**, SmallStack deliberately does *not* connect its
  own (two receivers would log every task twice) and reports **`tasks.W005`**
  from `manage.py check`. If you see it, alert on scheduler run status or
  `chain_outcome()` rather than on `django.tasks` `ERROR` until it's fixed.

A task that runs more than once is a separate signal and is *recorded*, not just
logged — see `background-tasks.md` → Reliability.

## Reading logs from a deployment you can't reach

Log lines are also written to the database (`apps.telemetry`), so they're readable from inside the app. This is the answer when the log *stream* isn't reachable — a locked-down container, a managed platform with no shell.

The viewer is **`/smallstack/logs/`** (staff only). Level / logger / time-range filters, search across messages *and* tracebacks, expandable rows for the traceback and `extra` fields, a live-poll mode, and the capture control in the header. Filter to one request with `?request_id=<id>` (a text box in the filter bar, or `/smallstack/activity/requests/` links straight there per request) or to one background job/pipeline with `?trace_id=<id>` (same text-box affordance — see "Tracing work that isn't a request" above; `apps.tasks` binds one automatically around every background task's execution, so this works for task log lines with zero setup).

The baseline is WARNING, which keeps the table small. When you need more, open a **capture window**: it turns the level up for a fixed period and closes itself.

```bash
uv run python manage.py log_capture status
uv run python manage.py log_capture start --level DEBUG --minutes 15
uv run python manage.py log_capture stop
```

The window can also be opened from the log viewer itself — the header shows what's being captured and has the control next to it, so you never need shell access. It lives in the database, so every worker and every container picks it up within one poll interval (5s) — including a process that starts *after* the window opened and hasn't logged anything at all. `TelemetryConfig.ready()` starts each handler's poller thread eagerly, before the process has done any work of its own, rather than waiting for a log call to trigger it — so this holds even for a freshly-started worker whose first lines are all below the baseline level (INFO/DEBUG while the baseline is WARNING). One caveat: if a deployment sets gunicorn's `preload_app = True` (the shipped `smallstack/gunicorn.conf` leaves it at the default `False`), the app loads once in the master before workers fork, and a thread started in the master doesn't survive `fork()` — under that specific config, each forked worker instead starts its poller lazily on its own first log line (of any level, not gated behind the level check), which still works but adds a small delay until that worker's first log line.

**If you turn on DEBUG and see nothing new**, the logger — not the handler — is what discarded it. A record has to be created before any handler is consulted, and `apps` sits at INFO in production. `TELEMETRY_CAPTURE_LOGGERS` lists the loggers whose level is lowered while a window is open; add yours if it isn't covered by `apps`, `smallstack`, or `django.request`.

`django.db.backends` is pinned at WARNING during capture no matter what — at DEBUG it emits one line per SQL query.

### Reading logs from a script or an agent — `/api/logger/`

The viewer is the human surface. For a CI job, a dev-tooling panel, or an AI agent driving a
debugging session, there's a read-only REST surface under `/api/logger/`, staff-only, Bearer or
session auth:

| Endpoint | Purpose |
|---|---|
| `GET /api/logger/` | Capability document — filters, limits, capture state |
| `GET /api/logger/records/` | Search records |
| `GET /api/logger/records/<id>/` | One record, full untruncated traceback |
| `GET /api/logger/capture/` | Capture-window status + this process's handler stats |

Filters match the viewer's exactly (same code path, so they can't drift): `level` (this level and
above), `logger` (hierarchy-aware prefix), `request_id`, `trace_id`, `search` (message **and**
traceback), `since`/`until` (ISO-8601), `after_id`, `limit`.

The payoff — resolving a user's request ID to the lines that explain it, without a browser:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://example.com/api/logger/records/?request_id=req_d09627b8-…"
```

Three behaviours worth knowing:

- **Unknown query parameters are a 400**, not silently ignored. A typo like `?sevrity=ERROR` would
  otherwise return the whole unfiltered table, which reads as a successful query.
- **Use `after_id` to tail**, not page numbers. It returns records strictly newer than a known id,
  oldest-first, with `next_after_id` to feed the next poll. Page numbers double-count when new
  rows arrive between polls.
- **List responses truncate tracebacks** and set `exc_truncated`; fetch the record's `url` for the
  full text.

Two more read endpoints round out discovery:

- `GET /api/logger/config/` — effective settings (`capture_enabled`, `baseline_level`,
  `capture_loggers`, retention, queue size) plus live handler stats. This is the provisioning
  check: *is capture even on, is my logger covered, am I dropping records?* A non-zero `dropped`
  means lines were lost under load rather than never logged. Read-only by design — persistent
  config belongs in settings/env.
- `GET /api/logger/loggers/` — logger names that have produced records, with counts, so a caller
  knows what to put in `?logger=` instead of guessing.

### Turning capture up over HTTP

```bash
# Open a window. `note` is required here (unlike the CLI) — an unattended client
# that turns production logging up should say why; operators read it in the viewer.
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"level":"DEBUG","minutes":15,"note":"agent: reproducing the 401"}' \
     https://example.com/api/logger/capture/
# 201 → {"open": true, "level": "DEBUG", "expires_at": "…", "clamped": false,
#         "poll_after_seconds": 5}

# Wait poll_after_seconds so other workers pick it up, reproduce, read, then:
curl -X DELETE -H "Authorization: Bearer $TOKEN" https://example.com/api/logger/capture/
```

`minutes` is clamped to `TELEMETRY_MAX_CAPTURE_MINUTES` and the response says `clamped: true`
when it was, rather than silently running for a different duration than you asked for. `DELETE`
is idempotent, so a cleanup step in a `finally` is safe even if the window already expired.
Opening and closing are audited via `LogEntry`, attributable to the token's user.

**A read-only token can read everything here but cannot open a window** (403). That's the right
credential for CI: it can assert an error was logged without being able to turn DEBUG on in
production.

### From an AI agent — MCP tools

Five tools, auto-registered with the MCP server (`apps/telemetry/mcp_tools.py`):

| Tool | Does |
|---|---|
| `logs_status` | Orientation: is capture on, at what level, is a window open, which loggers exist, are records being dropped. The first call to make. |
| `logs_search` | Same filters as `/api/logger/records/` — `request_id`, `trace_id`, `level`, `logger`, `search`, `since`/`until`, `after_id`. |
| `logs_get` | One record with the full traceback. |
| `logs_capture_start` | Turn capture up for a bounded window. `note` required. |
| `logs_capture_stop` | Back to baseline. Safe when nothing is open. |

Access matches the REST surface exactly: the **user** must be staff (the tools are hidden from
non-staff and refuse them at call time), and the two capture tools are `write=True`, so a
read-only token can investigate but cannot turn DEBUG on.

### From a shell — `manage.py logs`

Reading captured records no longer needs a browser:

```bash
manage.py logs --level ERROR --limit 20
manage.py logs --request-id req_d09627b8-…      # every line that request produced
manage.py logs --search ValidationError          # searches tracebacks too
manage.py logs --id 6183                         # one record, full traceback
manage.py logs --follow --level WARNING          # tail -f, cursor-based
manage.py logs --limit 5 --json                  # same payload as the API
```

An empty result says whether capture was simply at its baseline, which is the usual cause.
A bad filter exits non-zero with a usable message rather than a traceback.

`--json` is also on `log_capture start|stop|status` and `prune_logs`. Worth knowing why: the
human output of `log_capture status` printed a **Python dict repr** (single quotes, `False` not
`false`), so anything parsing it was screen-scraping something that was never JSON.

### What it costs

Nothing is written on the request path: records go onto a bounded queue and a background thread batches them out. If the app logs faster than the database absorbs it, records are dropped rather than blocking the request, and the drop is counted — `log_capture status` reports it. A non-zero `dropped` means raise `TELEMETRY_LOG_QUEUE_SIZE` or capture at a higher level.

Retention is enforced by `manage.py prune_logs` (wired into the container's cron every 15 minutes): records older than `TELEMETRY_LOG_RETENTION_DAYS` go, and a hard `TELEMETRY_LOG_MAX_ROWS` cap catches an incident that logs a million lines in ten minutes.

Set `TELEMETRY_LOG_CAPTURE_ENABLED=false` to switch the whole thing off — no handler, no queue, no thread, no rows.

## Audit with LogEntry

SmallStack provides `log_action()` and `AuditMixin` in `apps.smallstack.audit` for creating Django `LogEntry` records from non-admin code. No new models or migrations required.

### log_action()

Create an audit record manually:

```python
from apps.smallstack.audit import log_action, ADDITION, CHANGE, DELETION

# After creating an object
log_action(request.user, new_ticket, ADDITION, "Created via public form")

# After updating
log_action(request.user, ticket, CHANGE, "Escalated to priority P1")

# After deleting
log_action(request.user, ticket, DELETION)
```

### AuditMixin

Automatically log create/update actions in class-based views:

```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, UpdateView

from apps.smallstack.audit import AuditMixin


class TicketCreateView(AuditMixin, LoginRequiredMixin, CreateView):
    model = Ticket
    fields = ["title", "description", "priority"]


class TicketUpdateView(AuditMixin, LoginRequiredMixin, UpdateView):
    model = Ticket
    fields = ["status", "priority", "assigned_to"]
```

The mixin detects create vs update and logs which fields changed. Override `get_audit_message(form)` to customize:

```python
class TicketUpdateView(AuditMixin, LoginRequiredMixin, UpdateView):
    model = Ticket
    fields = ["status"]

    def get_audit_message(self, form):
        if "status" in form.changed_data:
            return f"Status changed to {form.instance.status}"
        return super().get_audit_message(form)
```

### Browsing audit logs

LogEntry is registered in Django admin at `/admin/admin/logentry/`. It shows all actions from both admin and `log_action()` calls, with filters for action type, content type, and user.
