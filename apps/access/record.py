"""Record one access change in the three places it belongs.

1. An :class:`~apps.access.models.AccessEvent` row: the durable, typed
   evidence the Access pages, the CSV export and the review list read.
2. A log line under ``apps.access`` (WARNING for a grant, INFO otherwise),
   carrying the request id, so it reaches ``/smallstack/logs/`` and the
   production JSON logs beside everything else that happened in the request.
3. A ``LogEntry`` on the affected account when a person made the change, so
   it also shows on that user's History page and in Django admin's history.

Recording never raises: an audit failure must not break the change it records,
and it is logged at ERROR so it is not silent either.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import Group
from django.db import transaction

from apps.smallstack.audit import CHANGE, log_action
from apps.smallstack.logging import get_request_id

from .context import current_actor, current_source
from .models import AccessEvent

logger = logging.getLogger(__name__)


def _label(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, Group):
        return obj.name
    get_username = getattr(obj, "get_username", None)
    return str(get_username() if get_username else obj)[:150]


def record(
    kind: str,
    *,
    subject: Any = None,
    group: Group | None = None,
    permission: str = "",
    detail: dict[str, Any] | None = None,
    actor: Any = None,
    source: str = "",
    subject_label: str = "",
    group_label: str = "",
) -> AccessEvent | None:
    """Record an access change. ``actor`` and ``source`` default to the
    current request's (see :mod:`apps.access.context`). ``subject_label`` /
    ``group_label`` name an account or group that is already gone (a delete),
    so the change log's filter and search still find it.

    The insert runs in its own savepoint: a failure rolls back only the
    audit row, never the caller's transaction (and the change it records)."""
    actor = actor if actor is not None else current_actor()
    source = source or current_source()
    try:
        with transaction.atomic():
            event = AccessEvent.objects.create(
                kind=kind,
                actor=actor,
                actor_label=_label(actor),
                subject=subject,
                subject_label=(_label(subject) or subject_label)[:150],
                group=group,
                group_label=(_label(group) or group_label)[:150],
                permission=permission,
                source=source[:200],
                request_id=get_request_id()[:64],
                detail=detail or {},
            )
    except Exception:
        logger.exception("access: could not record %s for %s", kind, _label(subject) or _label(group))
        return None

    message = _message(event)
    logger.log(
        logging.WARNING if event.is_grant else logging.INFO,
        "access: %s",
        message,
        extra={
            "access_kind": event.kind,
            "actor": event.actor_label or "system",
            "subject": event.subject_label,
            "group": event.group_label,
            "permission": event.permission,
            "source": event.source,
        },
    )
    # The account's History page, when a person made the change. A change with
    # no actor (a signup, a shell, a sync) is in the event table and the log;
    # writing it to history would mint the reserved system account on every
    # signup, and say nothing the event doesn't.
    if actor is not None and subject is not None and getattr(subject, "pk", None) is not None:
        try:
            log_action(actor, subject, CHANGE, message)
        except Exception:
            logger.exception("access: history entry for %s not written", event.subject_label)
    return event


def _message(event: AccessEvent) -> str:
    """One readable sentence for the log line and the account's history."""
    who = event.actor_label or "system"
    kind = AccessEvent.Kind(event.kind)
    subject, group, perm = event.subject_label, event.group_label, event.permission
    if kind == AccessEvent.Kind.GROUP_ADDED:
        return f"{who} added {subject} to group {group!r}"
    if kind == AccessEvent.Kind.GROUP_REMOVED:
        return f"{who} removed {subject} from group {group!r}"
    if kind == AccessEvent.Kind.PERMISSION_ADDED:
        return f"{who} granted {subject} the permission {perm} directly"
    if kind == AccessEvent.Kind.PERMISSION_REMOVED:
        return f"{who} removed the direct permission {perm} from {subject}"
    if kind == AccessEvent.Kind.GROUP_PERMISSION_ADDED:
        return f"{who} added the permission {perm} to group {group!r}"
    if kind == AccessEvent.Kind.GROUP_PERMISSION_REMOVED:
        return f"{who} removed the permission {perm} from group {group!r}"
    if kind == AccessEvent.Kind.TOKEN_REVOKED:
        return f"{who} revoked API token {event.detail.get('token', '')!r} of {subject}"
    if kind == AccessEvent.Kind.SESSIONS_ENDED:
        return f"{who} ended {event.detail.get('count', 0)} session(s) of {subject}"
    if kind == AccessEvent.Kind.GROUP_RENAMED:
        return f"{who} renamed group {event.detail.get('from', '')!r} to {group!r}"
    if kind in (AccessEvent.Kind.GROUP_CREATED, AccessEvent.Kind.GROUP_DELETED):
        return f"{who} {'created' if kind == AccessEvent.Kind.GROUP_CREATED else 'deleted'} group {group!r}"
    if kind == AccessEvent.Kind.REVIEW_SIGNED:
        d = event.detail
        return (
            f"{who} signed access review #{d.get('review_id', '?')} ({d.get('scope', '')}, "
            f"{d.get('period_start', '')} to {d.get('period_end', '')}): {d.get('confirmed', 0)} confirmed, "
            f"{d.get('remove', 0)} to remove, {d.get('flagged', 0)} flagged"
        )
    verbs = {
        AccessEvent.Kind.STAFF_ON: "made {s} staff",
        AccessEvent.Kind.STAFF_OFF: "removed staff from {s}",
        AccessEvent.Kind.SUPERUSER_ON: "made {s} a superuser",
        AccessEvent.Kind.SUPERUSER_OFF: "removed superuser from {s}",
        AccessEvent.Kind.ACTIVATED: "activated {s}",
        AccessEvent.Kind.DEACTIVATED: "deactivated {s}",
        AccessEvent.Kind.USER_CREATED: "created the account {s}",
        AccessEvent.Kind.USER_DELETED: "deleted the account {s}",
    }
    return f"{who} {verbs[kind].format(s=subject)}"
