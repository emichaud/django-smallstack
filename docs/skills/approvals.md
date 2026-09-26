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
recipients), `assignable=[…]` (whitelist for remote assignee selection, §2),
and `landing_url=fn(req) -> "/your/page/"` — where this kind sends its humans.
All four channels (both emails, both bell rows) use that one value, so a kind
that owns an embedded `{% approval_card %}` review page can point participants
there instead of the shared console. Unset ⇒ the console.

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
  `{"kind": …, "title": …, "context": {…}, "target": "app_label.model:pk",
  "assignees": ["username"], "expires_in_minutes": …}` → 201.
  Unknown kind → 400 listing the registered kinds. Readonly tokens can't file.
- **MCP** — the `request_approval` tool (any token tier; write-gated), then
  poll `get_approval` until `terminal` is true.

Both remote surfaces accept `target` and `assignees`, so a client does **not**
need an app-specific filing endpoint to point an approval at a business row:

- `target` is `"app_label.model:pk"` (or `{"app_label","model","pk"}`). It
  resolves through `ApprovalRequest.set_target`, so `req.target` is a real
  instance inside your kind callback. A malformed or unknown target is a 400.
- `assignees` is a list of usernames, and it is **refused unless the kind opts
  in** with `assignable=["finance", …]` (or `assignable=fn(user) -> bool`) — a
  remote caller must not be able to route a request at an arbitrary account.

Abuse model — the queue-flooding cap. One identity's outstanding **actionable**
requests per kind (pending *and* not yet overdue, the same definition the queue
and its stat card use — an expired-but-unswept request does not count against
you) are capped by `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER` (default 50,
`0` = no cap). Over the cap, `services.request_approval` raises `TooManyPending`
→ **429** on REST, `{"error": {"code": "too_many_pending"}}` on MCP. Without a
cap one agent in a loop buries every approver's bell, which defeats the gate by
fatigue rather than by a bug.

The cap is enforced in the **service**, so it applies to every caller — MCP, REST
and plain in-process Python alike. An agent is the likely offender, not the only
one; a runaway signal handler filing on every save hits it too.

## 3. Who may decide (the eligibility rules)

Eligibility lives in ONE place (`permissions.can_decide`) and is identical on
every surface — web console, embed, REST, MCP:

| Rule | Default | Setting |
|---|---|---|
| Only **active** accounts participate at all | — | — |
| Only pending requests can be decided | — | — |
| Self-approval is blocked | blocked | `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE` |
| With **assignees**: only they decide — plus staff | staff may override | `SMALLSTACK_APPROVALS_STAFF_OVERRIDE` |
| With **no assignees**: any staff decides | — | — |
| A kind's `can_decide` hook **ANDs** with the above | — | — |

The hook can *narrow* ("only the finance team") but can never *widen* past the
gates — returning `True` for a non-staff bystander changes nothing. A hook
that raises fails **closed**. Assignees may be non-staff: they decide on the
console (login-gated and eligibility-scoped — see §5) or in a
`{% approval_card %}` embed.

Cancel: the requester or staff, while pending.

**Deactivating an account (`is_active=False`) removes approval authority
everywhere, immediately.** This is enforced twice on purpose, because approvals
is the compliance control and no single layer should be load-bearing:

1. `APIToken.authenticate()` refuses to return a user whose account is inactive,
   so an already-minted, un-revoked bearer token stops working on **every**
   surface (REST 401 `Account is deactivated`, MCP 401, feeds, OAuth);
2. `permissions.can_view` / `can_decide` / `can_cancel` / `viewable_requests`
   treat an inactive account as absent, so even a live session decides nothing.

`emails.approver_users()` and `notify()` also both skip inactive users, so the
two channels agree about who exists.

**Token tiers (MCP).** `decide_approval` and the generated read tools are open
to any token tier; eligibility, not the tier, decides who may act. A token minted
by `POST /api/auth/token/` carries `access_level=""`, which means "whatever this
user is" — it is ranked from the account (`staff` when `is_staff`, else `auth`),
never as read-only. A token explicitly minted `readonly` still cannot write on
any surface.

## 4. What a decision fans out

One decision triggers, in order:

1. **The kind callback** — never breaks the decision; a raised exception lands
   in `callback_error` (surfaced on the console, and returned by the REST detail
   and the `get_approval` MCP tool so a remote caller can see it too).
2. **Audit** — a `LogEntry` with the source (`web` / `REST API` / `MCP` /
   `expiry`). Expiry has no human actor, so it is attributed to the reserved
   `SMALLSTACK_AUDIT_SYSTEM_USERNAME` account (created on first use as
   `is_active=False` with an unusable password — a label, not a credential).
   Set that setting blank to log system writes to the application log only.
3. **Signals** — `approval_requested` / `approval_decided`
   (`apps/approvals/signals.py`), sent on commit. `approval_decided` fires for
   **all** terminal transitions.
4. **In-app notifications** — see `notifications.md`.
   · on REQUEST: an `approvals.requested` row for each approver.
   · on DECISION: every `approvals.requested` row for that request is **marked
     read** (it is no longer work to do), then an `approvals.decided` row goes to
     the requester **and the other approvers** — the actor is auto-skipped.
     Rows carry `subject_key="approvals.request:<pk>"`, which is the handle
     approvals uses to retire them.
5. **Email** — branded. Recipients differ by event:
   · on REQUEST: the assignees (else staff-with-email) + `kind.notify` +
     `SMALLSTACK_APPROVALS_NOTIFY_EMAILS`, **minus the requester**.
   · on DECISION: the requester **and the approvers — including the one who
     decided** (being eligible is how they got to decide, so they are in the
     approver set), + `kind.notify` + `SMALLSTACK_APPROVALS_NOTIFY_EMAILS`.
   Inactive accounts are never mailed.

   > **The bell and the email differ by exactly one person, on purpose.** The
   > in-app notification skips the **actor** (`notifications/services.py` — you
   > don't need telling what you just did); the email does not. A bell row is a
   > *to-do* and the decider has none left; the decision email is the *record*,
   > and the decider is on the distribution for it like anyone else who was
   > accountable. `apps/approvals/emails.py`'s module docstring is the authority
   > for both rules — this section has been wrong in both directions before.
   >
   > **A routed request whose assignees are all deactivated falls back to every
   > active staff user**, because an approval must not go unseen. It is not
   > silent: a warning names the deactivated assignees, and the email subject and
   > bell title are prefixed `(assignee deactivated)`. Re-assign it.
   >
   > **The emailed link needs `SITE_DOMAIN`.** Approvals mail is sent from a
   > signal receiver or a task, so it has no request to derive a host from and
   > builds its absolute console URL from `SITE_DOMAIN` — `localhost:8000` by
   > default, which makes the link dead on any install that has not set it. That
   > matters most for the non-staff story ("assignees decide via the emailed
   > console link"). The Approvals status monitor reports it.

   > **Mail needs a worker, or `EMAILS_INLINE`.** Mail is queued on the `email`
   > task queue and **nothing is sent until a worker drains it**:
   > `manage.py db_worker --queue-name email`. Queuing is deliberate (a decision
   > must not wait on SMTP), and it is *not* self-healing: with the shipped
   > `DatabaseBackend` `enqueue()` never raises, so there is no "it fell back
   > inline" to rely on. Set `SMALLSTACK_APPROVALS_EMAILS_INLINE = True` to send
   > in-process instead — that is the **default in `DEBUG`**, so `make run` demos
   > and test runs deliver without a worker. In production the
   > `approvals-fanout` status monitor (`/smallstack/status/overview/`) goes DOWN
   > when approval email tasks sit unrun past
   > `SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES`, so the failure is loud.
6. **Webhooks** — `smallstack_approvals.approvalrequest.created` on filing and
   `.updated` on every transition; consumers read `data.status`
   (`enable_webhooks` on the CRUDView; subscribe from `/smallstack/webhooks/`).
   The inbound half of a pairing dispatches in
   `apps.webhooks.tasks.dispatch_incoming`, so **a paired SmallStack also does
   nothing until a worker runs** (see `webhooks.md`).

Remote reaction story: subscribe a webhook filtered on
`smallstack_approvals.approvalrequest.updated`, or poll the REST detail /
`get_approval` MCP tool until `status != "pending"`.

> **Pairing two SmallStack installs.** `sc webhook pair` configures both halves,
> and the receiver's `signature_header` defaults to the header our own sender
> emits (`X-SmallStack-Signature`), matched case-insensitively — so a default
> pairing verifies out of the box. One caveat with teeth: a **loopback or private
> target** (`http://127.0.0.1:…`, two instances on one box) is refused by the
> SSRF guard *before* the request leaves, recorded only as a failed delivery.
> Set `SMALLSTACK_WEBHOOK_ALLOW_PRIVATE=true` (dev only) in the **worker's**
> environment. `sc webhook pair` prints a warning when the target is blocked,
> and `sc doctor webhook` reports it.

## 5. The UI, and how to restyle it

- **Queue + console** — `/smallstack/approvals/requests/`: **login-gated and
  eligibility-scoped, not staff-gated.** Staff see every row; everyone else sees
  only rows they requested or are assigned (`permissions.viewable_requests` —
  existence-hiding, so an unrelated row is a 404, never a 403). This is
  deliberate: every link approvals sends a participant points here, and assignees
  may be non-staff. Filterable list (`?status=pending` is the queue) with
  pending/approved/rejected stat cards; the detail page is the decision console
  (Approve / Reject with a shared note, outcome band, callback-error band, kind
  context card). The same scoper governs the REST list **and detail** and the
  `list_approvals` / `get_approval` MCP tools, so a filing identity can always
  poll its own request. The sidebar entry stays staff-only.
- **Embed** — `{% load approvals_tags %}{% approval_card req %}` drops the
  decision card into any of your own pages — use it (plus `landing_url` on the
  kind) when you want participants on *your* page instead of the console.
  Also: `{% approval_can_decide user req as ok %}`.
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

**The cost model matters.** Expiring one row runs the whole fan-out — kind
callback, re-save, audit, signal, in-app notifications, an email task and a
webhook delivery — roughly 20 queries. So lazy expiry is **bounded**: a queue
load expires at most `SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT` rows (default 25,
most-overdue first, once per request) and logs a warning naming the sweep job
when a backlog remains. Unbounded it was 4,017 queries / 0.57 s for 200 overdue
rows and ~2.8 s for 1,000 — a gateway timeout on the approver's daily dashboard.

Because the flip is lazy, `status="pending"` and *actually awaiting a human* are
different sets. Use the queryset helpers rather than filtering `status` by hand,
so every reader agrees:

```python
ApprovalRequest.objects.pending()     # stored status, overdue rows included
ApprovalRequest.objects.overdue()     # pending and past expires_at
ApprovalRequest.objects.actionable()  # pending minus overdue — what a human can decide
```

`actionable()` is one cheap query with no fan-out; the dashboard widget, the
queue's "Pending" stat card and `services.pending_for()` all use it, which is why
the widget and the queue no longer disagree before a sweep runs.

## Settings (`config/settings/smallstack.py`)

| Setting | Default | Meaning |
|---|---|---|
| `SMALLSTACK_APPROVALS_ENABLED` | `True` | master switch — see below |
| `SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE` | `False` | let requesters decide their own |
| `SMALLSTACK_APPROVALS_STAFF_OVERRIDE` | `True` | staff may decide assigned requests |
| `SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES` | `0` | fallback TTL (0 = never) |
| `SMALLSTACK_APPROVALS_EMAILS_ENABLED` | `True` | email fan-out |
| `SMALLSTACK_APPROVALS_EMAILS_INLINE` | unset (`None`) → falls back to `DEBUG` | send mail in-process instead of queueing it. The value is genuinely `None` when unset; the `DEBUG` fallback is applied at the send site (`receivers.py`), so read it with that fallback rather than expecting `settings.…` to be a bool |
| `SMALLSTACK_APPROVALS_EMAIL_BACKLOG_MINUTES` | `15` | how long queued mail may sit before the monitor trips |
| `SMALLSTACK_APPROVALS_NOTIFY_EMAILS` | `[]` | extra recipients on every event |
| `SMALLSTACK_APPROVALS_SWEEP_ENABLED` | `True` | register the expiry sweep job |
| `SMALLSTACK_APPROVALS_LAZY_EXPIRE_LIMIT` | `25` | max rows one page-load may expire |
| `SMALLSTACK_APPROVALS_MAX_PENDING_PER_REQUESTER` | `50` | per-(requester, kind) pending cap (0 = none) |
| `SMALLSTACK_AUDIT_SYSTEM_USERNAME` | `"system"` | who actorless writes (expiry) are audited as |

**The master switch, precisely.** `SMALLSTACK_APPROVALS_ENABLED = False` means:

- the URLs are **not mounted** (`apps/smallstack/site_urls.py`) — no console, no
  REST, no decide POST, nothing to reverse;
- no kind autodiscovery, no receivers, no nav entry, no dashboard widget, no
  status monitor, and the `@scheduled` expiry sweep is **not registered**;
- `services.request_approval` / `decide` / `cancel` raise `ApprovalsDisabled`
  (→ **503** on REST/MCP), so a programmatic caller is told rather than silently
  half-served.

Anything that stops short of that — live endpoints with a dead fan-out — is worse
than no switch.

**Switching the sweep off on an existing install.** `SWEEP_ENABLED=False` stops
the *declaration*; the scheduler now also **disables** a `source=CODE`
`ScheduledJob` row whose spec has disappeared, so the flag takes effect on the
next sync instead of only on a fresh database. Operator-created (`source=UI`)
jobs are never touched. You can still disable or re-enable any job by hand at
`/smallstack/scheduler/`.

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
  resolvers.py      # target / assignees resolution shared by REST + MCP
  monitors.py       # status monitor: email backlog + unswept expiry backlog
  emails.py / tasks.py / dashboard_widgets.py
  templatetags/approvals_tags.py   # approval_context / approval_card
```
