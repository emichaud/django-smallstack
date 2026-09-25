---
title: Approvals
description: Generic human-in-the-loop approval workflow — @approval_kind, the decision console, and how apps react to decisions.
---

# Skill: Approvals (`apps/approvals/`)

A **side-car human-approval gate**: an app (or an AI agent) files an
`ApprovalRequest`, a human decides it in the console (or via the embeddable
card), and the app reacts to the decision through a per-kind callback — plus a
signal, a webhook event, and a pollable REST/MCP status for remote consumers.
What "approved" *means* stays app-owned: approvals never write your models for
you.

> **When to reach for it:** any action that needs a person to say yes first —
> publish a schedule, refund an order, let an agent run a risky operation. The
> canonical AI pattern is built in: an agent calls the `request_approval` MCP
> tool, then polls `get_approval` until a human decides.

State machine: `pending → approved | rejected | canceled | expired`. Every
transition is race-safe (conditional UPDATE, single winner), audited, and fires
the same fan-out.

## 1. Declare a kind (code-owned, autodiscovered)

Put an `approvals.py` in your app — it's autodiscovered at startup:

```python
# apps/calendar/approvals.py
from datetime import timedelta
from apps.approvals import approval_kind

@approval_kind("calendar.publish", label="Publish calendar schedule",
               default_expires_in=timedelta(days=3))
def on_publish_decision(req):
    """Runs after ANY terminal transition — read req.status."""
    schedule = req.target
    if schedule is None:
        return
    if req.status == req.Status.APPROVED:
        schedule.is_active = True
        schedule.save(update_fields=["is_active"])
    # rejected / expired / canceled: stays inactive — app-owned semantics
```

> **The callback fires for `expired` and `canceled` too**, not just
> approve/reject. If your kind arms something at request time, disarm it on
> every non-approved status. `on_decision` also accepts a dotted path string
> (`"apps.calendar.approvals.on_publish_decision"`) when import order is tricky.

Other `@approval_kind` kwargs: `description`, `can_decide=fn(user, req)`
(eligibility hook — **narrows only**, see below), `context_template="…"`
(explicit card template), `notify=["ops@example.com"]` (extra email
recipients).

Unregistered kinds are tolerated: a row whose kind key no longer exists still
renders (default card) and can be decided — its callback is a no-op. Rows
outlive code churn.

## 2. File a request

```python
from apps.approvals import services as approvals

req = approvals.request_approval(
    kind="calendar.publish",
    title=f"Publish “{schedule.name}”",
    actor=request.user,
    target=schedule,                        # any model instance (optional)
    context={"events": schedule.event_count},   # rendered on the decision card
    # assignees=[user1, user2],             # optional: narrows who may decide
    # expires_in=timedelta(hours=4),        # else kind default, else setting
)
```

Remote surfaces (both route through the same service):

- **REST** — `POST /smallstack/api/approvals/requests/create/` with
  `{"kind": …, "title": …, "context": {…}, "expires_in_minutes": …}` → 201.
  Unknown kind → 400 listing the registered kinds. Readonly tokens can't file.
- **MCP** — the `request_approval` tool (any token tier; write-gated), then
  poll `get_approval` until `status != "pending"`.

## 3. Who may decide (the eligibility rules)

Eligibility lives in ONE place (`permissions.can_decide`) and is identical on
every surface — web console, embed, REST, MCP:

| Rule | Default | Setting |
|---|---|---|
| Only pending requests can be decided | — | — |
| Self-approval is blocked | blocked | `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE` |
| With **assignees**: only they decide — plus staff | staff may override | `SMALLSTACK_APPROVALS_STAFF_OVERRIDE` |
| With **no assignees**: any staff decides | — | — |
| A kind's `can_decide` hook **ANDs** with the above | — | — |

The hook can *narrow* ("only the finance team") but can never *widen* past the
gates — returning `True` for a non-staff bystander changes nothing. A hook
that raises fails **closed**. Assignees may be non-staff: they decide via the
emailed console link or the `{% approval_card %}` embed (the decide endpoint
is eligibility-gated, not staff-gated).

Cancel: the requester or staff, while pending.

## 4. What a decision fans out

One decision triggers, in order:

1. **The kind callback** — never breaks the decision; a raised exception lands
   in `callback_error` (surfaced on the console).
2. **Audit** — a `LogEntry` with the source (`web` / `REST API` / `MCP` / `expiry`).
3. **Signals** — `approval_requested` / `approval_decided`
   (`apps/approvals/signals.py`), sent on commit. `approval_decided` fires for
   **all** terminal transitions.
4. **In-app notifications** — bell + inbox rows for the approvers on request,
   for the requester on decision (see `notifications.md`).
5. **Email** — branded, via the `email` task queue; recipients = assignees
   (else staff-with-email) + `kind.notify` + `SMALLSTACK_APPROVALS_NOTIFY_EMAILS`,
   minus the requester.
6. **Webhooks** — `smallstack_approvals.approvalrequest.created` on filing and
   `.updated` on every transition; consumers read `data.status`
   (`enable_webhooks` on the CRUDView; subscribe from `/smallstack/webhooks/`).

Remote reaction story: subscribe a webhook filtered on
`smallstack_approvals.approvalrequest.updated`, or poll the REST detail /
`get_approval` MCP tool until `status != "pending"`.

## 5. The UI, and how to restyle it

- **Queue + console** — `/smallstack/approvals/requests/` (staff): filterable
  list (`?status=pending` is the queue) with pending/approved/rejected stat
  cards; the detail page is the decision console (Approve / Reject with a
  shared note, outcome band, callback-error band, kind context card).
- **Embed** — `{% load approvals_tags %}{% approval_card req %}` drops the
  decision card into any of your own pages (this is how non-staff assignees
  decide). Also: `{% approval_can_decide user req as ok %}`.
- **Dashboard** — a pending-count widget on `/smallstack/`.

**Two template namespaces** (the app label is `smallstack_approvals` — house
prefix for common nouns):

| To override… | Create… |
|---|---|
| The decision console page | `templates/smallstack_approvals/crud/approvalrequest_detail.html` |
| The context card for ONE kind | `templates/approvals/kinds/<key with dots as dashes>.html` (e.g. `calendar-publish.html`) |
| The default context card | `templates/approvals/kinds/default.html` |

Card templates receive `req`, `kind`, `context`, `context_pretty`, `target`.
An explicit `context_template="…"` on the kind wins over the key-derived name.

## 6. Expiry

`expires_at` (explicit → `expires_in` → kind `default_expires_in` →
`SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES`; 0 = never). Overdue rows are
expired **lazily** (queue loads, decide attempts) — correctness never depends
on the worker — and by the `Approvals: expire overdue requests` scheduled
sweep (every 5m; see `scheduler.md`). Expiry runs the callback and fires
`approval_decided` with `source="expiry"`.

## Settings (`config/settings/smallstack.py`)

| Setting | Default | Meaning |
|---|---|---|
| `SMALLSTACK_APPROVALS_ENABLED` | `True` | master switch (app boots dark when off) |
| `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE` | `False` | let requesters decide their own |
| `SMALLSTACK_APPROVALS_STAFF_OVERRIDE` | `True` | staff may decide assigned requests |
| `SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES` | `0` | fallback TTL (0 = never) |
| `SMALLSTACK_APPROVALS_EMAILS_ENABLED` | `True` | email fan-out |
| `SMALLSTACK_APPROVALS_NOTIFY_EMAILS` | `[]` | extra recipients on every event |
| `SMALLSTACK_APPROVALS_SWEEP_ENABLED` | `True` | register the expiry sweep job |

## Files

```
apps/approvals/
  registry.py       # ApprovalKind + @approval_kind + first-wins registry
  models.py         # ApprovalRequest (status machine, target pointer)
  permissions.py    # can_view / viewable_requests / can_decide / can_cancel
  services.py       # request_approval, decide/approve/reject/cancel, mark_expired
  signals.py        # approval_requested / approval_decided (on-commit)
  receivers.py      # signal → in-app notification + email task
  views.py          # ApprovalRequestCRUDView + decide/cancel POSTs
  api.py            # POST create/ + {id}/decide/ (+ OpenAPI)
  mcp_tools.py      # request_approval + decide_approval
  emails.py / tasks.py / dashboard_widgets.py
  templatetags/approvals_tags.py   # approval_context / approval_card
```
