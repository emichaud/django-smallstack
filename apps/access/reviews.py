"""Periodic access reviews (attestations): the governance control over the
change log.

The log (:class:`AccessEvent`) is continuous: every grant and removal is
recorded as it happens. A review is deliberate: an attester opens one for a
period, which freezes the roster of accounts holding access at that moment,
decides each row (confirm, remove, flag), and signs. The signed review is
immutable evidence that a named person looked, on a date, and what they
concluded. Nothing here changes anyone's access: a *remove* decision files an
approval (``access.review_remove``) that a person holding
``accounts.change_user`` decides, and the deactivation runs through the same
paths and is recorded like any other change.

Every write goes through this module: :func:`open_review`, :func:`decide`,
:func:`confirm_all`, :func:`sign`. The pages and the CLI call these; REST and
MCP only read.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.smallstack.models import APIToken

from . import services
from .models import AccessEvent, AccessReview, AccessReviewItem, DirectoryIdentity
from .record import record

logger = logging.getLogger(__name__)

User = get_user_model()

#: Deciding a row and signing a review need this; the shipped *Access
#: attester* group grants it.
SIGN_REVIEW = "access.sign_accessreview"

#: Holding any of these makes an account *privileged* for the default scope,
#: beside the staff and superuser flags: it can change who has access, or
#: credentials.
PRIVILEGED_PERMISSIONS = frozenset(
    {
        "accounts.add_user",
        "accounts.change_user",
        "accounts.delete_user",
        "auth.change_group",
        "auth.delete_group",
        "auth.change_permission",
        "smallstack.add_apitoken",
        "smallstack.change_apitoken",
        "smallstack.delete_apitoken",
        SIGN_REVIEW,
    }
)


class ReviewRefused(PermissionError):
    """The actor may not do this to the review (→ a message on the page, a
    CommandError on the CLI)."""


# --- Who may --------------------------------------------------------------------


def attester_refusal(user: Any) -> str:
    """Why ``user`` may not decide rows or sign, or "". An active staff account
    holding :data:`SIGN_REVIEW`; **not** a superuser, since a superuser is
    what the review is about and an attestation by one of the reviewed
    accounts is worth little."""
    if user is None or not getattr(user, "is_authenticated", False) or not user.is_active:
        return "Signing in is required."
    if user.is_superuser:
        return "A superuser can't attest: superusers are what the review examines. Use an Access attester account."
    if not user.is_staff or not user.has_perm(SIGN_REVIEW):
        return f"Deciding and signing a review needs a staff account holding {SIGN_REVIEW} (the Access attester group)."
    return ""


def can_attest(user: Any) -> bool:
    return not attester_refusal(user)


def open_refusal(user: Any) -> str:
    """Why ``user`` may not open a review, or "": an attester, or a superuser
    (who may open but not sign)."""
    if user is not None and getattr(user, "is_superuser", False) and user.is_active:
        return ""
    return attester_refusal(user)


# --- The roster -------------------------------------------------------------------


def is_privileged(user: Any, perms: set[str] | None = None) -> bool:
    if user.is_superuser or user.is_staff:
        return True
    held = perms if perms is not None else user.get_all_permissions()
    return bool(PRIVILEGED_PERMISSIONS & held)


def roster_users(scope: str) -> list[Any]:
    """The active accounts a review of ``scope`` covers, by username."""
    users = User.objects.filter(is_active=True).prefetch_related("groups").order_by("username")
    if scope == AccessReview.Scope.ALL:
        return list(users)
    return [u for u in users if is_privileged(u)]


def _period_bounds(period_start: date, period_end: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(period_start, time.min), tz)
    end = timezone.make_aware(datetime.combine(period_end, time.max), tz)
    return start, end


def facts_for(user: Any, period_start: date, period_end: date) -> dict[str, Any]:
    """The account as the review will show it, frozen on the item."""
    start, end = _period_bounds(period_start, period_end)
    grants = user.get_all_permissions()
    direct = sorted(services.perm_name(p) for p in user.user_permissions.select_related("content_type"))
    grants_in_period = list(
        AccessEvent.objects.filter(subject=user, kind__in=AccessEvent.GRANTS, at__range=(start, end))
        .order_by("at")
        .values("at", "kind", "group_label", "permission", "actor_label", "source")[:50]
    )
    identities = list(
        DirectoryIdentity.objects.filter(user=user)
        .values("provider", "last_seen_at", "last_roles")
        .order_by("provider")
    )
    if identities:
        sign_in = "directory"
    elif user.has_usable_password():
        sign_in = "password"
    else:
        sign_in = "none"
    return {
        "username": user.get_username(),
        "email": user.email or "",
        "name": user.get_full_name() if user.get_full_name() != user.get_username() else "",
        "staff": user.is_staff,
        "superuser": user.is_superuser,
        "groups": sorted(g.name for g in user.groups.all()),
        "direct_permissions": direct,
        "permission_count": len(grants),
        "privileged_permissions": sorted(PRIVILEGED_PERMISSIONS & grants),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "date_joined": user.date_joined.isoformat(),
        "live_tokens": APIToken.objects.filter(user=user, is_active=True).count(),
        "sign_in": sign_in,
        "directory": [
            {
                "provider": i["provider"],
                "last_seen": i["last_seen_at"].isoformat() if i["last_seen_at"] else None,
                "roles": list(i["last_roles"] or []),
            }
            for i in identities
        ],
        "grants_in_period": [
            {
                "at": g["at"].isoformat(),
                "kind": g["kind"],
                "what": g["group_label"] or g["permission"] or "",
                "by": g["actor_label"] or "",
                "source": g["source"],
            }
            for g in grants_in_period
        ],
    }


def last_signed(scope: str, before: AccessReview | None = None) -> AccessReview | None:
    qs = AccessReview.objects.filter(scope=scope, status=AccessReview.Status.SIGNED)
    if before is not None:
        qs = qs.filter(Q(period_end__lt=before.period_end) | Q(period_end=before.period_end, pk__lt=before.pk))
    return qs.order_by("-period_end", "-pk").first()


def delta(review: AccessReview) -> dict[str, Any]:
    """Accounts on this roster that weren't on the previous signed review's
    (``new``), and the other way round (``gone``), with the ``previous``
    review's id. Empty lists and ``None`` with no previous review."""
    previous = last_signed(review.scope, before=review)
    now = set(review.items.values_list("user_label", flat=True))
    if previous is None:
        return {"new": [], "gone": [], "previous": None}
    then = set(previous.items.values_list("user_label", flat=True))
    return {"new": sorted(now - then), "gone": sorted(then - now), "previous": previous.pk}


# --- Periods ---------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    label: str
    start: date
    end: date

    @property
    def key(self) -> str:
        return f"{self.start.isoformat()}_{self.end.isoformat()}"


def quarter_of(day: date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3 + 1


def quarter_period(year: int, quarter: int) -> Period:
    start = date(year, 3 * (quarter - 1) + 1, 1)
    end_month = 3 * quarter
    end = date(year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
    return Period(f"Q{quarter} {year}", start, end)


def recent_quarters(n: int = 4, today: date | None = None) -> list[Period]:
    """The last ``n`` *complete* quarters, newest first: what the picker offers."""
    today = today or timezone.localdate()
    year, quarter = quarter_of(today)
    out: list[Period] = []
    for _ in range(n):
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        out.append(quarter_period(year, quarter))
    return out


def covered(period: Period) -> AccessReview | None:
    """A signed review whose period contains ``period``, any scope."""
    return (
        AccessReview.objects.filter(
            status=AccessReview.Status.SIGNED, period_start__lte=period.start, period_end__gte=period.end
        )
        .order_by("-signed_at")
        .first()
    )


# --- Writes ----------------------------------------------------------------------


def open_review(
    *,
    period_start: date,
    period_end: date,
    scope: str,
    actor: Any,
    note: str = "",
    request_id: str = "",
    source: str = AccessReview.Via.WEB,
) -> AccessReview:
    """Open a review and freeze its roster. Refuses when the period is
    inside-out, the scope unknown, the actor may not open one, or a review of
    that scope is already open (finish it first; two open rosters disagree).
    ``source`` records how: the page, the CLI, or the schedule."""
    refusal = open_refusal(actor) if actor is not None else ""
    if refusal:
        raise ReviewRefused(refusal)
    if scope not in AccessReview.Scope.values:
        raise ReviewRefused(f"scope must be one of {', '.join(AccessReview.Scope.values)}.")
    if period_end < period_start:
        raise ReviewRefused("The period ends before it starts.")
    if period_start > timezone.localdate():
        raise ReviewRefused("The period hasn't started; a review looks back.")
    existing = AccessReview.objects.filter(scope=scope, status=AccessReview.Status.OPEN).first()
    if existing is not None:
        raise ReviewRefused(f"Review #{existing.pk} ({existing.period_label}) is still open; sign it first.")
    with transaction.atomic():
        review = AccessReview.objects.create(
            period_start=period_start,
            period_end=period_end,
            scope=scope,
            opened_by=actor,
            opened_by_label=actor.get_username() if actor is not None else "",
            opened_via=source if source in AccessReview.Via.values else AccessReview.Via.WEB,
            note=note,
            request_id=request_id[:64],
        )
        AccessReviewItem.objects.bulk_create(
            [
                AccessReviewItem(
                    review=review,
                    user=user,
                    user_label=user.get_username()[:150],
                    facts=facts_for(user, period_start, period_end),
                )
                for user in roster_users(scope)
            ]
        )
    logger.info(
        "access: %s opened review #%s (%s, %s) with %s account(s)",
        review.opened_by_label or review.opened_via,
        review.pk,
        review.scope,
        review.period_label,
        review.items.count(),
    )
    return review


def decision_refusal(item: AccessReviewItem, decision: str, actor: Any) -> str:
    """Why ``actor`` may not record ``decision`` on ``item``, or ""."""
    if item.review.is_signed:
        return "This review is signed; its decisions can't change."
    if decision not in AccessReviewItem.Decision.values or decision == AccessReviewItem.Decision.PENDING:
        return "decision must be confirmed, remove or flagged."
    refusal = attester_refusal(actor)
    if refusal:
        return refusal
    if item.user_id is not None and item.user_id == actor.pk and decision != AccessReviewItem.Decision.FLAGGED:
        return "You can't confirm or remove your own access; flag your row for another attester."
    return ""


def decide(
    item: AccessReviewItem, decision: str, *, actor: Any, note: str = "", source: str = "web"
) -> AccessReviewItem:
    """Record one decision. *remove* also files an ``access.review_remove``
    approval for the account (the deactivation happens when someone holding
    ``accounts.change_user`` approves it) and notes it on the item."""
    refusal = decision_refusal(item, decision, actor)
    if refusal:
        raise ReviewRefused(refusal)
    note = (note or "").strip()  # whitespace is no note (G5-5)
    with transaction.atomic():
        follow_up = item.follow_up
        if (
            decision == AccessReviewItem.Decision.REMOVE
            and item.decision == AccessReviewItem.Decision.REMOVE
            and _removal_alive(follow_up)
            and item.note
            and note != item.note
        ):
            # The approval keeps the first reason; keep it on the row too
            # (T3-10), and an empty second note doesn't wipe it (G4-1).
            note = f"{item.note} · {note}" if note else item.note
        if decision == AccessReviewItem.Decision.REMOVE and not _removal_alive(follow_up):
            # Never filed, or the approval was canceled, rejected or expired:
            # deciding *remove* again files a new one (T3-3).
            follow_up = _file_removal(item, actor=actor, note=note, source=source)
        elif decision != AccessReviewItem.Decision.REMOVE and _withdraw_removal(follow_up, actor=actor):
            # The row no longer says remove: its pending approval goes (G2-2).
            follow_up = ""
        item.decision = decision
        item.decided_by = actor
        item.decided_by_label = actor.get_username()
        item.decided_at = timezone.now()
        item.note = note
        item.follow_up = follow_up
        item.save()
    return item


def approval_pk(follow_up: str) -> int | None:
    """The approval a row's ``follow_up`` points at (``approval:<pk>``), or None."""
    _, _, tail = follow_up.partition("approval:")
    return int(tail) if tail.isdigit() else None


def _removal_alive(follow_up: str) -> bool:
    """Whether ``follow_up`` names a removal approval that is still pending or
    was approved: anything else (none, canceled, rejected, expired) is dead."""
    from apps.approvals.models import ApprovalRequest

    pk = approval_pk(follow_up)
    if pk is None:
        return False
    req = ApprovalRequest.objects.filter(pk=pk).first()
    if req is None:
        return False
    return req.effective_status in (ApprovalRequest.Status.PENDING, ApprovalRequest.Status.APPROVED)


def _withdraw_removal(follow_up: str, *, actor: Any) -> bool:
    """Cancel the pending removal ``follow_up`` names, on behalf of the review
    (the decision changed). Returns whether one was withdrawn. The approval's
    own check also refuses it once the row no longer says *remove*, so a
    withdrawal that can't happen here still can't deactivate anyone."""
    from apps.approvals import services as approvals
    from apps.approvals.models import ApprovalRequest

    pk = approval_pk(follow_up)
    req = ApprovalRequest.objects.filter(pk=pk).first() if pk is not None else None
    if req is None or req.effective_status != ApprovalRequest.Status.PENDING:
        return False
    from apps.approvals.permissions import can_cancel

    who = actor if can_cancel(actor, req) else (req.requested_by or actor)
    note = f"The review's decision changed (by {actor.get_username()})."
    try:
        approvals.cancel(req, actor=who, note=note, source="review")
    except approvals.ApprovalError:
        return False
    return True


def _file_removal(item: AccessReviewItem, *, actor: Any, note: str, source: str) -> str:
    from apps.approvals import services as approvals

    from .approvals import REVIEW_REMOVE_KIND

    if item.user is None:
        return "account:gone"
    try:
        req = approvals.request_approval(
            kind=REVIEW_REMOVE_KIND.key,
            title=f"Deactivate {item.user_label} (access review #{item.review_id})",
            description=note or "An access review found this account should no longer hold access.",
            actor=actor,
            target=item.user,
            context={
                "username": item.user_label,
                "review_id": item.review_id,
                "period": item.review.period_label,
                "reason": note,
            },
            require_known_kind=True,
            source=source,
        )
    except approvals.ApprovalError as exc:
        raise ReviewRefused(f"Couldn't file the removal for approval: {exc}") from exc
    return f"approval:{req.pk}"


def confirm_all(review: AccessReview, *, actor: Any, item_pks: Iterable[int] | None = None) -> dict[str, int]:
    """Confirm every pending row (or the given ones) the actor may decide.
    The actor's own row is skipped, never confirmed by them. Returns counts."""
    refusal = attester_refusal(actor)
    if refusal:
        raise ReviewRefused(refusal)
    if review.is_signed:
        raise ReviewRefused("This review is signed; its decisions can't change.")
    qs = review.items.filter(decision=AccessReviewItem.Decision.PENDING)
    if item_pks is not None:
        qs = qs.filter(pk__in=list(item_pks))
    confirmed = skipped = 0
    for item in qs.select_related("review"):
        if item.user_id == actor.pk:
            skipped += 1
            continue
        decide(item, AccessReviewItem.Decision.CONFIRMED, actor=actor)
        confirmed += 1
    return {"confirmed": confirmed, "skipped": skipped}


def sign_refusal(review: AccessReview, actor: Any, typed_name: str) -> str:
    """Why ``actor`` may not sign, or "": an attester, every row decided, and
    the typed name is theirs (username or full name, case-insensitive)."""
    if review.is_signed:
        return "This review is already signed."
    refusal = attester_refusal(actor)
    if refusal:
        return refusal
    pending = review.items.filter(decision=AccessReviewItem.Decision.PENDING).count()
    if pending:
        return f"{pending} row{'s' if pending != 1 else ''} still pending: decide or flag every account first."
    typed = (typed_name or "").strip().casefold()
    names = {actor.get_username().casefold(), actor.get_full_name().strip().casefold()}
    if not typed or typed not in names:
        return "Type your username or full name to sign (capitals and spaces around it don't matter)."
    return ""


def sign(
    review: AccessReview,
    *,
    actor: Any,
    typed_name: str,
    note: str = "",
    request_id: str = "",
    signed_from: str = "",
) -> AccessReview:
    """Sign the review: it becomes immutable, and the signature is recorded
    as a ``review_signed`` access event with the counts. Then the cadence's
    follow-through (:func:`apps.access.cadence.after_signed`): the "review
    due" bells are retired, the attested evidence pack is stored, and the
    ``access.review.signed`` webhook event goes out — none of which can fail
    the signing."""
    refusal = sign_refusal(review, actor, typed_name)
    if refusal:
        raise ReviewRefused(refusal)
    counts = {
        "items": review.items.count(),
        **{
            key: review.items.filter(decision=value).count()
            for key, value in (
                ("confirmed", AccessReviewItem.Decision.CONFIRMED),
                ("remove", AccessReviewItem.Decision.REMOVE),
                ("flagged", AccessReviewItem.Decision.FLAGGED),
            )
        },
    }
    d = delta(review)
    with transaction.atomic():
        review.summary = {**counts, "new": d["new"], "gone": d["gone"], "previous": d["previous"]}
        review.signed_by = actor
        review.signed_by_label = actor.get_username()
        review.signed_at = timezone.now()
        review.signed_name = typed_name.strip()[:150]
        review.signed_from = signed_from[:64]
        # The opening's id stays in request_id; the signing's has its own (G2-6).
        review.signed_request_id = request_id[:64]
        if note:
            review.note = note
        review.status = AccessReview.Status.SIGNED
        review.save()
        record(
            AccessEvent.Kind.REVIEW_SIGNED,
            actor=actor,
            detail={
                "review_id": review.pk,
                "scope": review.scope,
                "period_start": review.period_start.isoformat(),
                "period_end": review.period_end.isoformat(),
                **counts,
            },
        )
    from . import cadence

    cadence.after_signed(review)
    return review


# --- Reads -----------------------------------------------------------------------


def unresolved_items() -> list[AccessReviewItem]:
    """Rows of signed reviews that still need someone: *flagged*, or *remove*
    while the account is still active, whatever became of its approval
    (pending, rejected, canceled, expired, never filed). A removal is resolved
    only when the account is deactivated or gone (T3-3): a withdrawn or
    rejected approval doesn't make the review's decision go away.

    Each *remove* item carries ``approval_state`` (the approval's effective
    status, or "not filed") for the finding's row."""
    from apps.approvals.models import ApprovalRequest

    items = list(
        AccessReviewItem.objects.filter(
            review__status=AccessReview.Status.SIGNED,
            decision__in=[AccessReviewItem.Decision.FLAGGED, AccessReviewItem.Decision.REMOVE],
        ).select_related("review", "user")
    )
    pks = [pk for pk in (approval_pk(i.follow_up) for i in items) if pk is not None]
    states = {r.pk: r.effective_status for r in ApprovalRequest.objects.filter(pk__in=pks)}
    out = []
    for item in items:
        if item.decision == AccessReviewItem.Decision.FLAGGED:
            out.append(item)
            continue
        if item.user is None or not item.user.is_active:
            continue
        pk = approval_pk(item.follow_up)
        item.approval_state = states.get(pk, "not filed") if pk is not None else "not filed"  # type: ignore[attr-defined]
        out.append(item)
    return out


def item_payload(item: AccessReviewItem, *, new: bool = False) -> dict[str, Any]:
    return {
        "username": item.user_label,
        "new": new,
        "decision": item.decision,
        "decided_by": item.decided_by_label or None,
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "note": item.note,
        "follow_up": item.follow_up,
        "facts": dict(item.facts or {}),
    }


def review_payload(review: AccessReview, *, items: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": review.pk,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "scope": review.scope,
        "status": review.status,
        "opened_by": review.opened_by_label or None,
        "opened_via": review.opened_via,
        "opened_at": review.opened_at.isoformat(),
        "signed_by": review.signed_by_label or None,
        "signed_at": review.signed_at.isoformat() if review.signed_at else None,
        "signed_name": review.signed_name,
        "signed_from": review.signed_from or None,
        "note": review.note,
        "request_id": review.request_id,
        "signed_request_id": review.signed_request_id or None,
        "summary": dict(review.summary or {}) if review.is_signed else live_counts(review),
    }
    if items:
        data["items"] = [item_payload(i, new=n) for i, n in ordered_items(review)]
    return data


def ordered_items(review: AccessReview) -> list[tuple[AccessReviewItem, bool]]:
    """The roster as the page shows it: accounts new since the scope's last
    signed review first (each paired with that ``new`` flag), then undecided,
    then by name. The CLI, REST and the exports use the same order (T3-14)."""
    new = set(delta(review)["new"])
    rows = [(item, item.user_label in new) for item in review.items.all()]
    rows.sort(key=lambda r: (not r[1], r[0].is_decided, r[0].user_label.lower()))
    return rows


def live_counts(review: AccessReview) -> dict[str, Any]:
    counts = {"items": 0, "pending": 0, "confirmed": 0, "remove": 0, "flagged": 0}
    for decision in review.items.values_list("decision", flat=True):
        counts["items"] += 1
        counts[decision] += 1
    return counts


REVIEW_CSV_COLUMNS = (
    "review",
    "period_start",
    "period_end",
    "scope",
    "username",
    "email",
    "staff",
    "superuser",
    "groups",
    "direct_permissions",
    "permission_count",
    "sign_in",
    "last_login",
    "live_tokens",
    "grants_in_period",
    "decision",
    "decided_by",
    "decided_at",
    "note",
    "follow_up",
    "signed_by",
    "signed_at",
    "new_since_last_review",  # appended, so existing column positions hold (T3-14)
)


def review_csv_rows(review: AccessReview) -> Iterable[dict[str, Any]]:
    """One row per item, every column flat, for the auditor's spreadsheet."""
    for item, new in ordered_items(review):
        f = item.facts or {}
        yield {
            "review": review.pk,
            "new_since_last_review": new,
            "period_start": review.period_start.isoformat(),
            "period_end": review.period_end.isoformat(),
            "scope": review.scope,
            "username": item.user_label,
            "email": f.get("email", ""),
            "staff": f.get("staff", False),
            "superuser": f.get("superuser", False),
            "groups": "; ".join(f.get("groups", [])),
            "direct_permissions": "; ".join(f.get("direct_permissions", [])),
            "permission_count": f.get("permission_count", 0),
            "sign_in": f.get("sign_in", ""),
            "last_login": f.get("last_login") or "",
            "live_tokens": f.get("live_tokens", 0),
            "grants_in_period": len(f.get("grants_in_period", [])),
            "decision": item.decision,
            "decided_by": item.decided_by_label,
            "decided_at": item.decided_at.isoformat() if item.decided_at else "",
            "note": item.note,
            "follow_up": item.follow_up,
            "signed_by": review.signed_by_label,
            "signed_at": review.signed_at.isoformat() if review.signed_at else "",
        }
