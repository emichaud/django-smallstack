"""Notification services — transport-agnostic, best-effort by contract.

`notify()` NEVER raises: a notification failure must not break the write that
triggered it (the runbook subscriptions discipline). Web views, REST, and
producers in other apps all call these functions, so behavior is identical on
every surface.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Iterable

from django.conf import settings
from django.utils import timezone

from .models import Notification

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger("smallstack.notifications")


def _real_users(recipients: Iterable[Any]) -> list[Any]:
    """Filter to saved, active, non-anonymous users, de-duplicated by pk."""
    seen: set[int] = set()
    users = []
    for user in recipients:
        pk = getattr(user, "pk", None)
        if pk is None or pk in seen or not getattr(user, "is_active", True):
            continue
        seen.add(pk)
        users.append(user)
    return users


def notify(
    recipients: Iterable[Any],
    *,
    title: str,
    message: str = "",
    url: str = "",
    kind: str = "",
    actor: Any = None,
    subject_key: str = "",
) -> int:
    """Create one Notification per recipient. Returns rows created.

    Best-effort: swallows every exception (logged), skips anonymous/unsaved/
    inactive users and the actor themselves (you don't need a bell for your
    own action). No-ops when SMALLSTACK_NOTIFICATIONS_ENABLED is off.

    ``subject_key`` is an optional producer-owned handle for *the thing this is
    about* (e.g. ``"approvals.request:42"``). Pass it and you can later call
    :func:`resolve` to retire every row about that subject — the missing piece
    that left stale "Approval needed" bells behind after someone decided.
    """
    if not getattr(settings, "SMALLSTACK_NOTIFICATIONS_ENABLED", True):
        return 0
    try:
        actor_pk = getattr(actor, "pk", None)
        users = [u for u in _real_users(recipients) if u.pk != actor_pk]
        if not users:
            return 0
        rows = Notification.objects.bulk_create(
            Notification(
                recipient=user,
                actor=actor if actor_pk is not None else None,
                title=title[:200],
                message=message,
                url=url[:300],
                kind=kind[:100],
                subject_key=subject_key[:200],
            )
            for user in users
        )
        return len(rows)
    except Exception:  # noqa: BLE001 — must never break the triggering write
        logger.exception("notifications: notify(%r) failed", title)
        return 0


def unread_count(user: Any) -> int:
    """Unread notifications for ``user`` — cheap (indexed) count for the bell."""
    if getattr(user, "pk", None) is None:
        return 0
    return Notification.objects.filter(recipient=user, read_at__isnull=True).count()


def mark_read(user: Any, ids: Iterable[int] | None = None) -> int:
    """Mark ``user``'s notifications read (all when ``ids`` is None).

    Only the recipient's own rows are touched — ids belonging to other users
    are silently ignored, so the endpoint can't be used to probe or mutate
    someone else's inbox.
    """
    if getattr(user, "pk", None) is None:
        return 0
    qs: QuerySet[Notification] = Notification.objects.filter(
        recipient=user, read_at__isnull=True
    )
    if ids is not None:
        qs = qs.filter(pk__in=list(ids))
    return qs.update(read_at=timezone.now())


def resolve(subject_key: str, *, kind: str = "") -> int:
    """Retire every unread row about ``subject_key``. Returns rows marked read.

    For producers whose notification means "there is work here": once the work
    is done, the pointer is noise. A bell that keeps counting finished work stops
    meaning "something to do", which is the only reason a bell exists. Never
    raises (same contract as :func:`notify`). Optionally narrow by ``kind`` so a
    producer can retire its "needed" rows while keeping its "decided" rows.
    """
    if not subject_key:
        return 0
    try:
        qs = Notification.objects.filter(subject_key=subject_key, read_at__isnull=True)
        if kind:
            qs = qs.filter(kind=kind)
        return qs.update(read_at=timezone.now())
    except Exception:  # noqa: BLE001 — must never break the triggering write
        logger.exception("notifications: resolve(%r) failed", subject_key)
        return 0


def prune(days: int | None = None) -> int:
    """Delete notifications older than the retention window. Returns count."""
    if days is None:
        days = int(getattr(settings, "SMALLSTACK_NOTIFICATIONS_RETENTION_DAYS", 90))
    if days <= 0:  # 0 = keep forever
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = Notification.objects.filter(created_at__lt=cutoff).delete()
    return deleted
