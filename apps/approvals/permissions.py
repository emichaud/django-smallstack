"""Approval permissions — the single source of truth (runbook canon).

Pure functions taking (user, obj) with matching queryset scopers, shared by
web views, REST, MCP, and the CLI so eligibility is identical on every
surface. No request objects here.

The decide policy, in order:
0. Only *active* accounts participate at all. Deactivating a user
   (``is_active=False``) is the standard offboarding action; it must remove
   approval authority everywhere, not just from web login. Defence in depth
   with ``APIToken.rejection_reason()`` (which refuses the credential), because
   approvals is a compliance control and must not depend on one layer.
1. Only authenticated, saved users decide, and only PENDING requests.
2. Self-approval is blocked (SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE flips it).
3. If the request names assignees: only they decide — plus staff when
   SMALLSTACK_APPROVALS_STAFF_OVERRIDE (default on; is_staff is the trust
   anchor, and an assignee-only request must not wedge permanently).
   With no assignees: any staff.
4. A registered kind's ``can_decide`` hook NARROWS the result (ANDed) — it can
   never widen past the gates above.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.db.models import Q, QuerySet

from .models import ApprovalRequest
from .registry import get_kind

logger = logging.getLogger(__name__)

Actor = Any  # User | AnonymousUser | None — the runbook Actor convention


def _pk(user: Actor) -> int | None:
    """The acting identity's pk, or None when it cannot act at all.

    A deactivated account is treated as absent on every approvals surface
    (see rule 0 in the module docstring).
    """
    if not getattr(user, "is_active", False):
        return None
    return getattr(user, "pk", None)


def is_staff(user: Actor) -> bool:
    return bool(getattr(user, "is_staff", False)) and bool(
        getattr(user, "is_active", False)
    )


def _hidden_kinds(user: Actor) -> list[str]:
    """Kinds whose ``view_permission`` ``user`` lacks (T3-9)."""
    from .registry import all_kinds

    return [k.key for k in all_kinds() if not may_view_kind(user, k)]


def may_view_kind(user: Actor, kind: Any) -> bool:
    """Whether a staff ``user`` passes ``kind.view_permission`` (any one of them)."""
    needed = kind.view_permission
    if not needed:
        return True
    perms = (needed,) if isinstance(needed, str) else tuple(needed)
    return any(user.has_perm(p) for p in perms)


def can_view(user: Actor, req: ApprovalRequest) -> bool:
    """Staff, the requester, or an assignee — active accounts only. A kind's
    ``view_permission`` narrows the staff part."""
    pk = _pk(user)
    if pk is None:
        return False
    if req.requested_by_id == pk:
        return True
    if req.assignees.filter(pk=pk).exists():
        return True
    if not is_staff(user):
        return False
    kind = get_kind(req.kind)
    return kind is None or may_view_kind(user, kind)


def viewable_requests(user: Actor, qs: QuerySet | None = None) -> QuerySet:
    """Scope a queryset to what ``user`` may see (existence-hiding: rows a
    viewer may not see are absent, never 403)."""
    if qs is None:
        qs = ApprovalRequest.objects.all()
    pk = _pk(user)
    if pk is None:
        return qs.none()
    own = Q(requested_by_id=pk) | Q(assignees__pk=pk)
    if is_staff(user):
        hidden = _hidden_kinds(user)
        if not hidden:
            return qs
        return qs.filter(~Q(kind__in=hidden) | own).distinct()
    return qs.filter(own).distinct()


def can_decide(user: Actor, req: ApprovalRequest) -> bool:
    pk = _pk(user)
    if pk is None or not req.is_pending:
        return False

    if req.requested_by_id == pk and not getattr(
        settings, "SMALLSTACK_APPROVALS_ALLOW_SELF_APPROVE", False
    ):
        return False

    if req.assignees.exists():
        eligible = req.assignees.filter(pk=pk).exists() or (
            is_staff(user)
            and getattr(settings, "SMALLSTACK_APPROVALS_STAFF_OVERRIDE", True)
        )
    else:
        eligible = is_staff(user)
    if not eligible:
        return False

    kind = get_kind(req.kind)
    if kind is not None and kind.can_decide is not None:
        try:
            return bool(kind.can_decide(user, req))
        except Exception:  # noqa: BLE001 — a broken hook must fail CLOSED
            # Closed is right, but say why: otherwise an eligible approver is
            # refused with nothing anywhere to explain it.
            logger.exception("can_decide hook for approval kind %r raised; refusing request %s", req.kind, req.pk)
            return False
    return True


def can_cancel(user: Actor, req: ApprovalRequest) -> bool:
    """The requester or staff may withdraw a pending request; a registered
    kind's ``can_cancel`` hook NARROWS that (ANDed, failing closed), as
    ``can_decide`` does for deciding."""
    pk = _pk(user)
    if pk is None or not req.is_pending:
        return False
    if not (req.requested_by_id == pk or is_staff(user)):
        return False
    kind = get_kind(req.kind)
    if kind is not None and kind.can_cancel is not None:
        try:
            return bool(kind.can_cancel(user, req))
        except Exception:  # noqa: BLE001 — a broken hook must fail CLOSED
            logger.exception("can_cancel hook for approval kind %r raised; refusing request %s", req.kind, req.pk)
            return False
    return True
