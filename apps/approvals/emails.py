"""Approval emails + recipient computation — best-effort, swallow everything.

Recipient rules, as the code below actually computes them. Read this before
editing ``docs/skills/approvals.md`` §4 — that section has been wrong twice, in
both directions, and the difference between "the other approvers" and "the
approvers" is the whole of it.

**on REQUEST** — :func:`approver_users`, plus the kind's ``notify`` list and
``SMALLSTACK_APPROVALS_NOTIFY_EMAILS``:

* the request's **active** assignees; if it has none (or all of them are
  deactivated), every **active staff** user with an email address;
* always **minus the requester** — you don't need a nudge for your own ask.

**on DECISION** — the same :func:`approver_users` set, **plus the requester**,
plus the kind's ``notify`` list and the setting. Note what that means and what it
does not:

* the **decider is mailed too**, whenever they are one of the approvers — which
  they almost always are, since being eligible is how they got to decide. The
  set is "the approvers", *not* "the other approvers".
* the requester is mailed even though they were excluded on REQUEST.

**The bell and the email deliberately differ on exactly one point.** The in-app
notification skips the **actor** (``apps/notifications/services.py`` — "you don't
need to be told what you just did"), and the email does not. This is intentional,
not an oversight: a bell row is a *to-do* and the decider has nothing left to do,
while the decision email is the *record* of the decision and the decider is on
the distribution for it, the same as anyone else who was accountable for the
request. If you change one channel, change this docstring and both ``.md`` files
in the same commit.

A mail failure must never break the request/decision that triggered it
(runbook subscriptions discipline).
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import ApprovalRequest
from .registry import get_kind, resolve_landing_url

logger = logging.getLogger("smallstack.approvals")


def _console_path(req: ApprovalRequest) -> str:
    return reverse("approvals/requests-detail", kwargs={"pk": req.pk})


def landing_path(req: ApprovalRequest) -> str:
    """Where a participant should be sent for ``req``.

    Used by all four channels (request email, request bell row, decision email,
    decision bell row) so they can never disagree. A kind may override it with
    ``landing_url=`` to point at its own embedded review page; otherwise this is
    the shared console, which is login-gated and eligibility-scoped — reachable
    by non-staff assignees and requesters, who are the usual recipients. (F-01.)
    """
    return resolve_landing_url(get_kind(req.kind), req) or _console_path(req)


def routing_is_broken(req: ApprovalRequest) -> bool:
    """True when the request named assignees and none of them can be reached.

    "Nobody was ever named" and "everybody named has been offboarded" are
    different facts with the same empty assignee list, and treating them the same
    turned a request deliberately routed to one named approver into a broadcast to
    every staff member the moment that person was deactivated — 1 recipient and 1
    bell became 6 recipients and 10 bells, carrying the request's title and
    context to everyone with staff. That is the opposite of what an approvals gate
    should do with a routing failure. (F-32.)
    """
    named = list(req.assignees.all())
    return bool(named) and not any(u.is_active for u in named)


def approver_users(req: ApprovalRequest) -> list[Any]:
    """The humans who should hear about a new request (User objects).

    Deactivated accounts are excluded in BOTH branches: an offboarded assignee
    used to keep receiving mail (while ``notify()`` correctly dropped them), so
    the two channels disagreed about who exists. (F-09.)

    When every named assignee is gone the staff fallback still applies — the
    request must not go unseen — but it is no longer *silent*: the fan-out logs a
    warning naming the deactivated assignees, and the subject line says why
    everyone is being told (see :func:`subject_prefix`). (F-32.)
    """
    named = list(req.assignees.all())
    assignees = [u for u in named if u.is_active]
    if assignees:
        return [u for u in assignees if u.pk != req.requested_by_id]

    if named:
        logger.warning(
            "approvals: request %s (%r) was routed to %s, but every named assignee "
            "is deactivated — falling back to ALL active staff. Re-assign it: a "
            "routed request has become a broadcast.",
            req.pk,
            req.title,
            ", ".join(sorted(u.get_username() for u in named)),
        )
    users = list(get_user_model().objects.filter(is_staff=True, is_active=True))
    return [u for u in users if u.pk != req.requested_by_id]


def subject_prefix(req: ApprovalRequest) -> str:
    """"(assignee deactivated) " when the request's routing has broken, else "".

    Put in the subject so a staff user who suddenly receives a request they were
    never assigned can tell *why*, instead of reading it as normal traffic. (F-32.)
    """
    return "(assignee deactivated) " if routing_is_broken(req) else ""


def _extra_emails(req: ApprovalRequest) -> list[str]:
    kind = get_kind(req.kind)
    extras = list(kind.notify) if kind else []
    extras += list(getattr(settings, "SMALLSTACK_APPROVALS_NOTIFY_EMAILS", []) or [])
    return extras


def _send(subject: str, template: str, context: dict[str, Any], to: list[str]) -> int:
    """Branded multipart send; returns recipients reached (0 on any failure)."""
    to = sorted({e for e in to if e})
    if not to:
        return 0
    try:
        from apps.accounts.emails import send_branded_email

        return send_branded_email(subject=subject, template=template, context=context, to=to)
    except Exception:  # noqa: BLE001 — email must never break the transition
        logger.exception("approvals: email %r failed", subject)
        return 0


def send_requested(pk: int) -> int:
    if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
        return 0
    req = ApprovalRequest.objects.filter(pk=pk).first()
    if req is None:
        return 0
    recipients = [u.email for u in approver_users(req) if u.email] + _extra_emails(req)
    return _send(
        subject=f"Approval needed: {subject_prefix(req)}{req.title}",
        template="email/approval_requested.html",
        context={"req": req, "console_path": landing_path(req)},
        to=recipients,
    )


def send_decided(pk: int) -> int:
    if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
        return 0
    req = ApprovalRequest.objects.filter(pk=pk).first()
    if req is None:
        return 0
    # The requester (it was their ask) AND the approvers — INCLUDING the decider,
    # who is normally in approver_users() because being eligible is how they got
    # to decide. Mailing only the requester left every other approver of a
    # multi-approver request with an "Approval needed" mail and no follow-up, for
    # the rest of time. (F-13.) See the module docstring for why this set differs
    # from the bell's by exactly the actor. (F-04.)
    recipients = _extra_emails(req)
    recipients += [u.email for u in approver_users(req) if u.email]
    requester_email = getattr(req.requested_by, "email", "")
    if requester_email:
        recipients.append(requester_email)
    return _send(
        subject=f"{req.get_status_display()}: {req.title}",
        template="email/approval_decided.html",
        context={"req": req, "console_path": landing_path(req)},
        to=recipients,
    )
