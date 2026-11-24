"""The access-review cadence: the control runs on a calendar, not on memory.

A daily scheduled job (:mod:`apps.access.tasks`) calls :func:`tick`. When a
quarter has closed with no signed review covering it, the tick **opens** the
review (so the roster is frozen on a predictable date), **stores** the
quarter's evidence pack (:class:`EvidenceBundle`, with its SHA-256) and tells
the attesters in-app and by email that it is due. While the review stays open
it **reminds** them every few days, and once it is past due it **escalates**:
the attesters and ``SMALLSTACK_ACCESS_REVIEW_ESCALATION_EMAILS`` hear once,
and the *Access review overdue* finding turns danger. When a review is signed
(:func:`after_signed`, called from :func:`apps.access.reviews.sign`), the
bells are retired, the attested pack is stored, and the
``access.review.signed`` webhook event goes out.

Signing is still a human act: nothing here decides a row or signs. The tick
is idempotent — running it twice a day, or after a week of downtime, does
nothing it hasn't already done.

**Opt-in.** ``SMALLSTACK_ACCESS_REVIEW_CADENCE`` is off by default: no job is
scheduled, nothing is sent, the dashboard shows no card, and reviews and the
evidence pack stay on demand from the pages and the CLI. Most deployments
never turn it on; the ones with an auditor's calendar set it to ``quarterly``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import date, timedelta
from typing import Any

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import evidence, reviews
from .models import AccessReview, EvidenceBundle

logger = logging.getLogger(__name__)

User = get_user_model()

#: The outbound webhook event a signing emits (``register_event`` puts it in
#: the endpoint picker).
EVENT_SIGNED = "access.review.signed"
#: The dotted path of the scheduled task, for the schedule's row.
TASK_PATH = "apps.access.tasks.review_cadence"


# --- Settings ---------------------------------------------------------------------


def cadence() -> str:
    return str(getattr(settings, "SMALLSTACK_ACCESS_REVIEW_CADENCE", "quarterly") or "")


def enabled() -> bool:
    return cadence() == "quarterly"


def scope() -> str:
    value = str(getattr(settings, "SMALLSTACK_ACCESS_REVIEW_SCOPE", "privileged") or "privileged")
    return value if value in AccessReview.Scope.values else AccessReview.Scope.PRIVILEGED


def due_days() -> int:
    return max(0, int(getattr(settings, "SMALLSTACK_ACCESS_REVIEW_DUE_DAYS", 30)))


def reminder_days() -> int:
    return max(0, int(getattr(settings, "SMALLSTACK_ACCESS_REVIEW_REMINDER_DAYS", 7)))


def escalation_emails() -> list[str]:
    return [e for e in (getattr(settings, "SMALLSTACK_ACCESS_REVIEW_ESCALATION_EMAILS", []) or []) if e]


def keep() -> int:
    return max(0, int(getattr(settings, "SMALLSTACK_ACCESS_EVIDENCE_KEEP", 24)))


# --- Who, when -----------------------------------------------------------------------


def attesters() -> list[Any]:
    """The accounts that can sign: active staff holding ``SIGN_REVIEW`` and not
    a superuser (:func:`reviews.attester_refusal`)."""
    candidates = User.objects.filter(is_active=True, is_staff=True, is_superuser=False).order_by("username")
    return [u for u in candidates if reviews.can_attest(u)]


def due_date(review: AccessReview) -> date:
    return review.period_end + timedelta(days=due_days())


def is_overdue(review: AccessReview, today: date | None = None) -> bool:
    return (today or timezone.localdate()) > due_date(review)


def status(today: date | None = None) -> dict[str, Any]:
    """Where the control stands, for the Reviews page and the dashboard
    widget: the last complete quarter and whether it is signed or open, when
    it is due, the last signing, when the current quarter closes, the
    schedule's row."""
    today = today or timezone.localdate()
    period = reviews.recent_quarters(1, today)[0]
    signed = reviews.covered(period)
    open_ = AccessReview.objects.filter(status=AccessReview.Status.OPEN).order_by("period_end", "pk").first()
    due = period.end + timedelta(days=due_days())
    last = AccessReview.objects.filter(status=AccessReview.Status.SIGNED).order_by("-signed_at").first()
    current = reviews.quarter_period(*reviews.quarter_of(today))
    return {
        "enabled": enabled(),
        "cadence": cadence(),
        "scope": scope(),
        "period": period,
        "signed": signed,
        "open": open_,
        "due": due,
        "days_until_due": (due - today).days,
        "days_overdue": max(0, (today - due).days),
        "last_signed": last,
        "next_close": current.end,
        "job": scheduled_job(),
    }


def scheduled_job() -> Any:
    """The scheduler's row for the cadence task, or ``None`` (cadence off —
    a row left from when it was on is retired at the next start and isn't
    the schedule — scheduler not installed, or not synced yet)."""
    if not enabled() or not django_apps.is_installed("apps.scheduler"):
        return None
    try:
        from apps.scheduler.models import ScheduledJob

        return ScheduledJob.objects.filter(task_path=TASK_PATH).first()
    except Exception:  # noqa: BLE001 — a status read must never break the page
        return None


# --- The tick --------------------------------------------------------------------------


def tick(today: date | None = None) -> dict[str, Any]:
    """One pass: open the review for a closed quarter and store its pack, then
    remind or escalate every open review. Returns what it did."""
    today = today or timezone.localdate()
    now = timezone.now()
    out: dict[str, Any] = {"opened": None, "bundle": None, "reminded": [], "escalated": [], "pruned": 0}
    if not enabled():
        out["skipped"] = "SMALLSTACK_ACCESS_REVIEW_CADENCE is off; reviews are opened by hand."
        return out

    period = reviews.recent_quarters(1, today)[0]
    sc = scope()
    if (
        reviews.covered(period) is None
        and not AccessReview.objects.filter(scope=sc, status=AccessReview.Status.OPEN).exists()
    ):
        review = reviews.open_review(
            period_start=period.start,
            period_end=period.end,
            scope=sc,
            actor=None,
            note=f"{period.label} access review, opened by the schedule.",
            source=AccessReview.Via.SCHEDULE,
        )
        AccessReview.objects.filter(pk=review.pk).update(reminded_at=now)
        out["opened"] = review.pk
        try:
            bundle = store_bundle(
                period.start, period.end, sc, reason=EvidenceBundle.Reason.PERIOD_CLOSED, review=review
            )
            out["bundle"] = bundle.pk
        except Exception:  # noqa: BLE001 — the review is open; the pack can be stored by hand
            logger.exception("access: storing the %s evidence pack failed", period.label)
        notify_review(review, "opened")

    # The one opened just now was told its due date a moment ago; a late start
    # (the quarter closed weeks ago) escalates on the next tick, not the same one.
    for review in AccessReview.objects.filter(status=AccessReview.Status.OPEN).exclude(pk=out["opened"] or 0):
        last = review.reminded_at or review.opened_at
        if review.escalated_at is None and today > due_date(review):
            notify_review(review, "overdue")
            AccessReview.objects.filter(pk=review.pk).update(
                escalated_at=now, reminded_at=now, reminders=review.reminders + 1
            )
            out["escalated"].append(review.pk)
        elif reminder_days() and last <= now - timedelta(days=reminder_days()):
            told = notify_review(review, "reminder")
            # Count a reminder only when someone could receive it (T5-6); the
            # tick still moves reminded_at so the warning isn't logged daily.
            sent = 1 if told.get("attesters") else 0
            AccessReview.objects.filter(pk=review.pk).update(reminded_at=now, reminders=review.reminders + sent)
            if sent:
                out["reminded"].append(review.pk)

    out["pruned"] = prune_bundles()
    return out


def after_signed(review: AccessReview) -> None:
    """What a signing sets in motion, none of which may fail the signing:
    retire the "review due" bells, store the attested pack, emit the webhook."""
    try:
        from apps.notifications import resolve

        resolve(subject_key(review))
    except Exception:  # noqa: BLE001
        logger.exception("access: retiring review notifications failed")
    try:
        store_bundle(
            review.period_start,
            review.period_end,
            review.scope,
            reason=EvidenceBundle.Reason.REVIEW_SIGNED,
            actor=review.signed_by,
            review=review,
        )
    except Exception:  # noqa: BLE001
        logger.exception("access: storing the attested evidence pack for review #%s failed", review.pk)
    try:
        emit_signed(review)
    except Exception:  # noqa: BLE001
        logger.exception("access: emitting %s for review #%s failed", EVENT_SIGNED, review.pk)


# --- Telling the attesters ---------------------------------------------------------


def subject_key(review: AccessReview) -> str:
    return f"access.review:{review.pk}"


def _wording(review: AccessReview, event: str) -> tuple[str, str]:
    counts = reviews.live_counts(review)
    quarter = next(
        (q.label for q in reviews.recent_quarters(8) if (q.start, q.end) == (review.period_start, review.period_end)),
        review.period_label,
    )
    due = due_date(review)
    pending = counts["pending"]
    if event == "opened":
        return (
            f"Access review due: {quarter}",
            f"{counts['items']} account{'s' if counts['items'] != 1 else ''} to decide and sign by {due:%b %d, %Y}.",
        )
    if event == "overdue":
        return (
            f"Access review overdue: {quarter}",
            f"Due {due:%b %d, %Y}; {pending} of {counts['items']} still pending. "
            "The control isn't operating until it is signed.",
        )
    return (
        f"Access review still open: {quarter}",
        f"{pending} of {counts['items']} pending · due {due:%b %d, %Y}.",
    )


def notify_review(review: AccessReview, event: str) -> dict[str, int]:
    """Tell the attesters (in-app and by email) that ``review`` was opened, is
    still open, or is overdue. ``overdue`` also mails the escalation list.
    Never raises."""
    people = attesters()
    title, message = _wording(review, event)
    path = reverse("access:review_detail", kwargs={"pk": review.pk})
    out = {"bells": 0, "emails": 0, "attesters": len(people)}
    try:
        from apps.notifications import notify

        out["bells"] = notify(
            people,
            title=title,
            message=message,
            url=path,
            kind=f"access.review.{event}",
            subject_key=subject_key(review),
        )
    except Exception:  # noqa: BLE001
        logger.exception("access: review notification failed")
    to = [u.email for u in people if u.email]
    if event == "overdue":
        to += escalation_emails()
    out["emails"] = _send(
        subject=title,
        context={
            "review": review,
            "event": event,
            "title": title,
            "message": message,
            "counts": reviews.live_counts(review),
            "due": due_date(review),
            "console_path": path,
            "no_attesters": not people,
        },
        to=to,
    )
    if not people:
        what = {"opened": "was opened", "reminder": "needs a reminder", "overdue": "is overdue"}.get(event, event)
        logger.warning(
            "access: review #%s %s, but no account can sign it (an active staff member holding %s, "
            "not a superuser): nobody was told",
            review.pk,
            what,
            reviews.SIGN_REVIEW,
        )
    return out


def _send(*, subject: str, context: dict[str, Any], to: list[str]) -> int:
    to = sorted({e for e in to if e})
    if not to:
        return 0
    try:
        from apps.accounts.emails import send_branded_email

        return int(send_branded_email(subject=subject, template="email/access_review_due.html", context=context, to=to))
    except Exception:  # noqa: BLE001 — mail must never break the tick
        logger.exception("access: review email %r failed", subject)
        return 0


# --- Stored packs ---------------------------------------------------------------------------


def store_bundle(
    period_start: date,
    period_end: date,
    scope: str,
    *,
    reason: str = EvidenceBundle.Reason.MANUAL,
    actor: Any = None,
    review: AccessReview | None = None,
    label: str = "schedule",
) -> EvidenceBundle:
    """Build the pack for the period, zip it, and keep it with its SHA-256.
    Then apply retention for the scope. ``label`` names who built it when
    there is no ``actor`` (``schedule`` for the cadence, ``cli`` for a local
    command)."""
    who = actor if getattr(actor, "pk", None) is not None else None
    pack = evidence.build(period_start, period_end, scope=scope, generated_by=who or label)
    data = evidence.bundle_zip(pack)
    stamp = timezone.localtime(pack.generated_at)
    name = f"{evidence.bundle_name(pack)}-{stamp:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}.zip"
    bundle = EvidenceBundle(
        period_start=period_start,
        period_end=period_end,
        scope=scope,
        reason=reason,
        review=review,
        built_by=who,
        built_by_label=pack.generated_by,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        counts={s.key: s.count for s in pack.sheets},
    )
    with transaction.atomic():
        bundle.file.save(name, ContentFile(data), save=False)
        bundle.save()
    logger.info(
        "access: stored evidence pack #%s (%s, %s, %s, %s bytes, sha256 %s)",
        bundle.pk,
        pack.period_label,
        scope,
        reason,
        bundle.size,
        bundle.sha256[:12],
    )
    prune_bundles(scope)
    return bundle


def prune_bundles(scope: str | None = None) -> int:
    """Keep the newest ``SMALLSTACK_ACCESS_EVIDENCE_KEEP`` bundles per scope
    **and reason**; delete the rest (file included). 0 keeps every one.
    Counting each reason apart means packs stored on request can only push
    out older on-request packs, never the one a quarter's close or a signing
    kept for the auditor (T4-2). Returns how many were deleted."""
    limit = keep()
    if limit <= 0:
        return 0
    scopes = [scope] if scope else list(AccessReview.Scope.values)
    deleted = 0
    for sc in scopes:
        for reason in EvidenceBundle.Reason.values:
            stale = list(
                EvidenceBundle.objects.filter(scope=sc, reason=reason).order_by("-built_at", "-pk")[limit:]
            )
            for bundle in stale:
                bundle.delete()
                deleted += 1
    return deleted


def bundle_payload(bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "id": bundle.pk,
        "period_start": bundle.period_start.isoformat(),
        "period_end": bundle.period_end.isoformat(),
        "scope": bundle.scope,
        "reason": bundle.reason,
        "review": bundle.review_id,
        "built_at": bundle.built_at.isoformat(),
        "built_by": bundle.built_by_label or None,
        "filename": os.path.basename(bundle.file.name or ""),
        "size": bundle.size,
        "sha256": bundle.sha256,
        "counts": dict(bundle.counts or {}),
    }


# --- The webhook event --------------------------------------------------------------------


def register_event() -> None:
    """Put ``access.review.signed`` in the webhook endpoint picker."""
    if not django_apps.is_installed("apps.webhooks"):
        return
    try:
        from apps.webhooks import services as webhooks

        webhooks.register_event(EVENT_SIGNED, "an access review is signed")
    except Exception:  # noqa: BLE001
        logger.exception("access: registering the %s webhook event failed", EVENT_SIGNED)


def signed_payload(review: AccessReview, event_id: str) -> dict[str, Any]:
    """The event envelope, shaped like a CRUDView's (``event``, ``action``,
    ``model``, ``id``, ``occurred_at``, ``data``, ``event_id``, ``origin``,
    ``resource``) so a consumer handles both the same way."""
    origin = ""
    try:
        from apps.webhooks import current_origin

        origin = current_origin()
    except Exception:  # noqa: BLE001
        pass
    url = None
    if origin.startswith(("http://", "https://")):
        try:
            url = origin.rstrip("/") + reverse("access-api-review", kwargs={"review_id": review.pk})
        except Exception:  # noqa: BLE001
            url = None
    return {
        "event": EVENT_SIGNED,
        "action": "signed",
        "model": "access.accessreview",
        "id": review.pk,
        "occurred_at": timezone.now().isoformat(),
        "data": reviews.review_payload(review, items=False),
        "event_id": event_id,
        "origin": origin,
        "resource": {"type": "access.accessreview", "id": review.pk, "url": url},
    }


def emit_signed(review: AccessReview) -> int:
    """Fan ``access.review.signed`` out to every endpoint whose filter matches.
    Returns deliveries created (0 when the webhooks app is absent or off)."""
    if not django_apps.is_installed("apps.webhooks"):
        return 0
    from apps.webhooks import services as webhooks

    event_id = str(uuid.uuid4())
    return webhooks.fan_out(EVENT_SIGNED, signed_payload(review, event_id), event_id=event_id)
