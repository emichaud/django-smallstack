"""Document subscriptions — a demo consumer of the ``document_written`` event.

Users subscribe to a document; when it's written, an async fan-out emails them.
This is deliberately small and self-contained to show the extension pattern:
subscribe/unsubscribe helpers, a subscribers query, and the notification sender
that the task (and inline fallback) call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.mail import send_mail
from django.db.models import QuerySet

from .models import Document, Subscription

if TYPE_CHECKING:
    from apps.accounts.models import User as UserType

logger = logging.getLogger(__name__)

User = get_user_model()


def _subscriber(user: AbstractBaseUser | AnonymousUser) -> "UserType":
    """Narrow an actor to the concrete User the subscriber FK stores."""
    return cast("UserType", user)


def subscribe(user: AbstractBaseUser | AnonymousUser, document: Document) -> Subscription:
    subscription, _ = Subscription.objects.get_or_create(subscriber=_subscriber(user), document=document)
    return subscription


def unsubscribe(user: AbstractBaseUser | AnonymousUser, document: Document) -> None:
    Subscription.objects.filter(subscriber=_subscriber(user), document=document).delete()


def is_subscribed(user: AbstractBaseUser | AnonymousUser, document: Document) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return Subscription.objects.filter(subscriber=_subscriber(user), document=document).exists()


def subscribers_of(document: Document) -> QuerySet:
    """The users subscribed to ``document``."""
    return User.objects.filter(runbook_subscriptions__document=document)


def send_update_notifications(document_id: int, change_type: str) -> int:
    """Email a document's subscribers about an update. Returns the recipient count.

    Called by ``notify_subscribers_task`` (async) or inline as a fallback.
    """
    doc = Document.objects.filter(pk=document_id).select_related("runbook").first()
    if doc is None:
        return 0
    recipients = list(subscribers_of(doc).exclude(email="").values_list("email", flat=True))
    if not recipients:
        return 0

    where = doc.runbook.name if doc.runbook else "Runbook"
    # Notifying subscribers must never break the document save that triggered
    # it — swallow delivery errors (replaces the deprecated fail_silently=True).
    try:
        send_mail(
            subject=f"[Runbook] {doc.title} was updated",
            message=f'"{doc.title}" in {where} changed ({change_type}).',
            from_email=None,
            recipient_list=recipients,
        )
    except Exception:
        logger.exception("Runbook subscriber notification failed for %s", doc.pk)
        return 0
    return len(recipients)
