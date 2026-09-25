# notifications — in-app notifications (bell + inbox)

A generic in-app notification primitive: any app calls
`apps.notifications.notify(recipients, title=..., url=..., kind=...)` and the
recipients get a topbar-bell badge plus an inbox row that deep-links back.
Approvals is the first producer; use it for anything a signed-in user should
notice on their next visit.

**Status:** Framework-provided. Enabled by default
(`SMALLSTACK_NOTIFICATIONS_ENABLED`); the bell hides and `notify()` no-ops
when off.

**The contract:** `notify()` never raises, skips the actor / anonymous users /
duplicate recipients, and returns the number of rows created. `mark_read` is
always recipient-scoped. `kind` is a free-form dotted key (`"<app>.<event>"`) —
no registry.

**Surfaces:** topbar bell with unread count (context processor), the
LoginRequired inbox at `/smallstack/notifications/` (mark-read redirect guards
against open redirects and cross-user access), per-user REST
(`GET /smallstack/notifications/api/`, `POST …/mark-read/`), and the daily
`Notifications: prune old rows` sweep (`SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS`,
default 90).

**Key files:** `models.py` (`Notification`), `services.py`
(`notify`/`unread_count`/`mark_read`/`prune`), `context_processors.py`,
`views.py`, `api.py`, `tasks.py`.

**See:** [`../../docs/skills/notifications.md`](../../docs/skills/notifications.md) ·
first producer: [`../approvals/`](../approvals/).
