---
title: Notifications
description: In-app notifications — the notify() service, the topbar bell, and the inbox.
---

# Skill: Notifications (`apps/notifications/`)

A generic **in-app notification** primitive: any app calls `notify()` and the
recipients get a topbar bell badge plus an inbox row that deep-links back to
your page. Approvals is the first producer (`approvals.requested` /
`approvals.decided`); use the same call for anything a signed-in user should
notice on their next visit.

> **When to reach for it:** "the user should see this next time they're here."
> For "the user must hear about this NOW even if away," send an email too
> (`send_branded_email`) — the two channels are complementary, not exclusive.

## Producing notifications

```python
from apps.notifications import notify

notify(
    [user_a, user_b],                 # or any iterable of Users
    title="Approval needed: Publish “Winter”",
    message="Calendar publish",       # optional second line
    url="/smallstack/approvals/requests/42/",   # internal path to open
    kind="approvals.requested",       # dotted producer key — yours to invent
    actor=request.user,               # who caused it; actors are auto-skipped
    subject_key=f"approvals.request:{req.pk}",   # optional handle — see below
)
```

Contract (all enforced in `services.notify`, tested):

- **Never raises** — a notification failure must not break the action that
  caused it. Returns the number of rows created.
- Skips the `actor` (you don't need a bell for your own action), anonymous /
  unsaved users, **inactive (`is_active=False`) users**, and duplicate
  recipients in one call.
- Gated on `SMALLSTACK_NOTIFICATIONS_ENABLED` — returns 0 when off (and the bell,
  inbox and REST routes are not mounted at all).
- `kind` is a free-form dotted key (`"<app>.<event>"` by convention). Use it
  for querying/pruning; there is no registry to declare.

### Retiring your own rows (`subject_key` + `resolve`)

A notification that means "there is work here" becomes noise the moment the work
is done. `notify()` is otherwise fire-and-forget, so pass an opaque
producer-owned `subject_key` naming *the thing this is about*, then retire every
row about it when it stops being actionable:

```python
from apps.notifications import resolve

resolve(f"approvals.request:{req.pk}", kind="approvals.requested")  # → rows marked read
```

`resolve` is recipient-agnostic (it retires the row for everyone who got one),
optionally narrowed by `kind`, idempotent, a no-op on a blank key, and never
raises. Approvals uses it so that when one of several approvers decides, nobody
is left with an unread "Approval needed" bell pointing at a settled request.

Other services: `unread_count(user)`, `mark_read(user, ids=None)` (always
recipient-scoped — one user can never mark another's rows).

## What the user sees

- **Topbar bell** — for authenticated users, with an unread-count badge
  (via the `notifications` context processor; hidden when the app is disabled).
- **Inbox** — `/smallstack/notifications/` (LoginRequired, NOT staff-only —
  producers like approvals notify non-staff users). Unread rows are dotted;
  clicking routes through a redirect (internal paths only, cross-user rows 404);
  "Mark all read" clears the badge.

> **Read is an outcome, not an intention.** The click-through redirect appends
> `?_notification=<pk>`, and `NotificationReadOnArrivalMiddleware` marks the row
> read only when the target answers **2xx**. A click that lands on a 403 or a
> stale 404 leaves the row unread, so a dead-end link can't silently consume the
> badge and take the user's only pointer with it. (An empty or non-internal url
> has nothing to arrive at, so it is marked read immediately.) The middleware is
> in `MIDDLEWARE` by default and costs one dict lookup per request.

## REST

- `GET /smallstack/notifications/api/` — the current user's rows
  (`?unread=1`, `limit=` ≤ 200) plus `unread_total`.
- `POST /smallstack/notifications/api/mark-read/` — `{"ids": [...]}` or
  `{"all": true}`.

Both are per-user (token = the user); there's no admin CRUD surface or MCP
tool — agents poll the producing feature (e.g. approvals) directly. Rows include
`subject_key`, and both paths declare their response shape plus their `400`/`401`
(`/403`) responses in `/api/schema/openapi.json`.

## Retention

The `Notifications: prune old rows` scheduled job (daily, see `scheduler.md`)
deletes rows older than `SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS`
(default 90; `0` keeps forever).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `SMALLSTACK_NOTIFICATIONS_ENABLED` | `True` | master switch (bell hidden, notify() no-ops) |
| `SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS` | `90` | prune horizon (0 = keep forever) |

## Files

```
apps/notifications/
  models.py             # Notification (recipient, actor, title, url, kind, subject_key, read_at)
  services.py           # notify() / unread_count() / mark_read() / resolve() / prune()
  middleware.py         # mark-read-on-arrival (2xx) for click-throughs
  context_processors.py # notifications_enabled + notifications_unread (the bell)
  views.py              # inbox, open-and-mark-read redirect, mark-all-read
  api.py                # GET list + POST mark-read (+ OpenAPI)
  tasks.py              # daily prune (@scheduled)
  templates/notifications/inbox.html
```
