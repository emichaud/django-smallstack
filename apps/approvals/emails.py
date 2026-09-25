"""Approval emails + recipient computation — best-effort, swallow everything.

The recipient rule (shared by email and in-app notification):
- on REQUEST: the assignees; with none, every staff user with an email —
  plus the kind's ``notify`` list and SMALLSTACK_APPROVALS_NOTIFY_EMAILS,
  always minus the requester (you don't need a nudge for your own ask).
- on DECISION: the requester, plus the kind's ``notify`` list and the setting.

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
from .registry import get_kind

logger = logging.getLogger("smallstack.approvals")


def _console_path(req: ApprovalRequest) -> str:
    return reverse("approvals/requests-detail", kwargs={"pk": req.pk})


def approver_users(req: ApprovalRequest) -> list[Any]:
    """The humans who should hear about a new request (User objects)."""
    assignees = list(req.assignees.all())
    if assignees:
        users = assignees
    else:
        users = list(
            get_user_model().objects.filter(is_staff=True, is_active=True)
        )
    return [u for u in users if u.pk != req.requested_by_id]


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
        subject=f"Approval needed: {req.title}",
        template="email/approval_requested.html",
        context={"req": req, "console_path": _console_path(req)},
        to=recipients,
    )


def send_decided(pk: int) -> int:
    if not getattr(settings, "SMALLSTACK_APPROVALS_EMAILS_ENABLED", True):
        return 0
    req = ApprovalRequest.objects.filter(pk=pk).first()
    if req is None:
        return 0
    recipients = _extra_emails(req)
    requester_email = getattr(req.requested_by, "email", "")
    if requester_email:
        recipients.append(requester_email)
    return _send(
        subject=f"{req.get_status_display()}: {req.title}",
        template="email/approval_decided.html",
        context={"req": req, "console_path": _console_path(req)},
        to=recipients,
    )
