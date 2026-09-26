---
title: Approvals
description: A generic human-in-the-loop approval gate — apps or AI agents file a request, a person decides, your code reacts
---

# Approvals

> **Building this?** Read the agent-facing skill first: [`docs/skills/approvals.md`](https://github.com/emichaud/django-smallstack/blob/main/docs/skills/approvals.md). It's prescriptive (what to do); this page is the reference (why + worked examples).

Some actions need a person to say yes before they happen: publishing a schedule, issuing a refund, letting an AI agent run something sensitive. Approvals is the generic version of that gate — a **side-car workflow** that any app plugs into without inheriting anyone else's business rules.

The shape is deliberate: your app files an `ApprovalRequest`, a human decides it in the console at `/smallstack/approvals/requests/`, and your app reacts to the outcome. Approvals never writes your models for you — what "approved" *means* stays entirely yours.

The same loop is the canonical AI-agent pattern: an agent calls the `request_approval` MCP tool, a person approves or rejects in the console, and the agent polls `get_approval` until the status changes.

## The lifecycle

Every request moves `pending → approved | rejected | canceled | expired`. Transitions are race-safe (two people deciding simultaneously produce exactly one winner), audited with their source (web / REST / MCP / expiry), and all fan out the same way.

## Declaring a kind

A *kind* gives a request meaning: a label for humans, a callback for the decision, an optional TTL and card template. Declare kinds in your app's `approvals.py` — it's autodiscovered at startup:

```python
# apps/calendar/approvals.py
from datetime import timedelta
from apps.approvals import approval_kind

@approval_kind("calendar.publish", label="Publish calendar schedule",
               default_expires_in=timedelta(days=3))
def on_publish_decision(req):
    schedule = req.target
    if schedule is None:
        return
    if req.status == req.Status.APPROVED:
        schedule.is_active = True
        schedule.save(update_fields=["is_active"])
```

> The callback runs after **every** terminal transition — including `expired` and `canceled` — so read `req.status`. If your kind arms something at request time, disarm it on every non-approved outcome.

## Filing a request

```python
from apps.approvals import services as approvals

approvals.request_approval(
    kind="calendar.publish",
    title=f"Publish “{schedule.name}”",
    actor=request.user,
    target=schedule,                      # optional model pointer
    context={"events": schedule.event_count},  # shown on the decision card
)
```

Or remotely: `POST /smallstack/api/approvals/requests/create/` (REST) or the `request_approval` MCP tool. Both reject unknown kinds with an error listing the registered ones.

## Who may decide

One rule set, enforced identically on every surface:

- Any **staff** user decides by default; **self-approval is blocked** (`SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE` flips it).
- Naming **assignees** on a request narrows deciding to them — staff can still step in unless you turn off `SMALLSTACK_APPROVALS_STAFF_OVERRIDE`.
- A kind's `can_decide` hook can narrow further ("only the finance team") but can never widen past those gates.

Assignees don't need to be staff, and **deactivating an account removes its approval authority immediately** — on the web, over REST, and over MCP, even if it still holds a valid API token.

Non-staff participants aren't second-class here: the console is login-gated and scoped by eligibility, so a requester or assignee opens the very link the email and the bell row give them, and sees only their own rows. You can also point a kind's humans at your own page with `landing_url=`, or drop the embeddable card straight into it:

```django
{% load approvals_tags %}
{% approval_card req %}
```

## How everyone finds out

A new request notifies its eligible deciders; a decision notifies the requester and the approvers (and retires their now-stale "Approval needed" bell, so the badge keeps meaning "work to do"). The two channels differ by exactly one person, deliberately: the **bell skips whoever acted** — you don't need telling what you just did — while the **email includes the decider**, because it is the record of the decision rather than a to-do — via the in-app bell ([Notifications](/smallstack/help/smallstack/notifications/)), branded email, an `approval_decided` signal, and an outbound webhook (`smallstack_approvals.approvalrequest.updated`, with the new status in `data.status`). Remote systems can subscribe to that event or just poll the REST detail until `status != "pending"`.

One operational caveat worth knowing before you demo it: email is **queued** on the `email` task queue, so a deployment with no `db_worker` sends nothing. That's on purpose (a decision shouldn't wait on SMTP) and it's visible — the Approvals status monitor goes down when mail piles up unsent. In `DEBUG` the mail is sent in-process instead, so local runs just work.

## Expiry

Requests can carry a TTL (per request, per kind, or the global `SMALLSTACK_APPROVALS_DEFAULT_EXPIRES_MINUTES`). Overdue requests expire lazily whenever they're touched — plus a background sweep every 5 minutes — and expiry runs the kind callback like any other outcome, recorded in the audit trail under the reserved system account since no human caused it.

Lazy expiry is capped per page-load, because expiring a request runs its whole fan-out. A large backlog is drained by the sweep, not by whoever happened to open the queue first.

## Customizing the UI

- Override the whole decision console: `templates/smallstack_approvals/crud/approvalrequest_detail.html`.
- Restyle the context card for one kind: `templates/approvals/kinds/<key-with-dashes>.html` (e.g. `calendar-publish.html`) — the card receives `req`, `kind`, `context`, `context_pretty`, and `target`.

## Related

- [Notifications](/smallstack/help/smallstack/notifications/) — the in-app bell + inbox channel approvals fan out to
- [Webhooks](/smallstack/help/smallstack/webhooks/) — the `.updated` event decisions ride on
- [Background Tasks](/smallstack/help/smallstack/background-tasks/) — the queue behind email fan-out and the expiry sweep
- [MCP](/smallstack/help/smallstack/mcp/) — how agents reach `request_approval` / `decide_approval`
