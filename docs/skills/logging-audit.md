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

### Request IDs for correlation

Every request gets a unique `X-Request-ID` via `RequestIDMiddleware` (first in the middleware stack). Access it as `request.id` in views and middleware. The ID is returned in the response header and stored in `RequestLog.request_id`, making it easy to correlate user-reported errors to specific log entries.

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
