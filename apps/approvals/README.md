# approvals — human-in-the-loop approval gate

A generic **side-car approval workflow**: an app (or an AI agent over MCP)
files an `ApprovalRequest`, a human approves/rejects it in the themed console
(or the `{% approval_card %}` embed), and the app reacts via a per-kind
callback, a signal, a webhook event, or by polling. What "approved" *means*
stays app-owned — approvals never write your models for you.

**Status:** Framework-provided. Enabled by default (`SMALLSTACK_APPROVALS_ENABLED`);
harmless with zero kinds registered.

**Declare a kind** in your app's `approvals.py` (autodiscovered):
`@approval_kind("calendar.publish", default_expires_in=timedelta(days=3))` on the
function that reacts to the decision (`req.status` is any terminal state —
**including `expired`/`canceled`**). File with
`services.request_approval(kind=..., title=..., actor=..., target=..., context=...)`.

**Eligibility (one implementation, every surface):** any staff decides by
default; self-approval blocked (`_ALLOW_SELF_APPROVE`); per-request
`assignees` narrow it (staff can still override — `_STAFF_OVERRIDE`); a kind's
`can_decide` hook ANDs on top. Assignees may be non-staff — they decide via
the embed or the emailed console link.

**Surfaces:** staff queue + decision console at `/smallstack/approvals/requests/`
(CRUDView: list/detail, search, filters, stat cards), REST
(`POST …/create/`, `POST …/{id}/decide/` + the CRUD poll surface), MCP
(`request_approval`, `decide_approval` + factory list/get), outbound webhooks
(`smallstack_approvals.approvalrequest.created`/`.updated` — decisions carry
`data.status`), in-app notifications + branded email fan-out, a `/smallstack/`
dashboard widget, and the `Approvals: expire overdue requests` sweep (expiry
is also lazy, so correctness never depends on the worker).

**Key files:** `registry.py` (`@approval_kind`), `models.py` (`ApprovalRequest`),
`permissions.py` (the single eligibility source), `services.py` (race-safe
transitions), `receivers.py`/`emails.py` (fan-out),
`templatetags/approvals_tags.py` (`approval_context`, `approval_card`).

**See:** [`../../docs/skills/approvals.md`](../../docs/skills/approvals.md) ·
notifications channel in [`../notifications/`](../notifications/).
