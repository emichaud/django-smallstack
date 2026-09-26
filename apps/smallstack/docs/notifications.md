---
title: Notifications
description: In-app notifications — a notify() call becomes a topbar bell badge and an inbox row that links back to your page
---

# Notifications

> **Building this?** Read the agent-facing skill first: [`docs/skills/notifications.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/notifications.md).

When something happens that a signed-in user should notice on their next visit — an approval waiting on them, a task that finished, a mention — call `notify()` and they get a **topbar bell badge** plus a row in their **inbox** at `/smallstack/notifications/` that deep-links back to your page.

Approvals ships wired into it; the surface is generic and yours to use.

```python
from apps.notifications import notify

notify(
    [user_a, user_b],
    title="Approval needed: Publish “Winter”",
    message="Calendar publish",                  # optional second line
    url="/smallstack/approvals/requests/42/",    # internal path to open
    kind="approvals.requested",                  # your dotted key, e.g. "<app>.<event>"
    actor=request.user,                          # actors are auto-skipped
)
```

The contract is designed so producers never have to think about failure:

- `notify()` **never raises** — a notification problem can't break the action that caused it. It returns the number of rows created.
- It skips the actor (no bell for your own action), anonymous and unsaved users, **deactivated accounts**, and duplicate recipients.
- Pass an optional `subject_key="myapp.thing:42"` and you get a handle back: `resolve("myapp.thing:42")` marks every row about that thing read, for everyone who got one. Use it the moment your notification stops being work to do — a bell that counts finished work stops meaning anything.
- With `SMALLSTACK_NOTIFICATIONS_ENABLED = False` the bell disappears and `notify()` quietly returns 0.
- `kind` is free-form — no registry to declare. Use it to group, query, and prune.

## The inbox

Login-required but **not staff-only** — producers like approvals notify ordinary users too. Unread rows are marked, clicking a row follows its link (internal paths only; another user's rows 404), and "Mark all read" clears the badge.

A row is marked read when you actually *arrive* — not when you click. If the link turns out to be unreachable for you (a 403, a stale 404), the row stays unread, so a dead end can't quietly take the badge and your only pointer to the thing with it.

## For other apps and scripts

- `GET /smallstack/notifications/api/` — the calling token's own rows (`?unread=1`, `limit=`), plus an `unread_total`.
- `POST /smallstack/notifications/api/mark-read/` — `{"ids": [...]}` or `{"all": true}`.

Everything is scoped to the requesting user; there's no cross-user admin API. When it's email you need ("must hear about this even if away"), send one alongside — the two channels complement each other.

## Retention

A daily background job prunes rows older than `SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS` (default 90; `0` keeps everything).

## Related

- [Approvals](/smallstack/help/smallstack/approvals/) — the first producer (bell on request, bell on decision)
- [Background Tasks](/smallstack/help/smallstack/background-tasks/) — runs the daily prune
