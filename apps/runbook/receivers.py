"""Built-in event consumers — runbook wiring its own features to the domain
signals. Connected in ``apps.RunbookConfig.ready()``.

Retention's version-pruning is itself a consumer of ``document_written``, which
dogfoods the extension seam downstream apps use.
"""

from __future__ import annotations

from typing import Any

from django.dispatch import receiver

from . import signals
from .models import Document


@receiver(signals.document_written, dispatch_uid="runbook_prune_on_write")
def prune_on_write(
    sender: Any, document: Document, change_type: str, **kwargs: Any
) -> None:
    """Bound a document's history right after a new version is added."""
    if change_type != "new_version":
        return
    _enqueue_prune(document.pk)


@receiver(signals.document_written, dispatch_uid="runbook_notify_subscribers")
def notify_subscribers_on_write(
    sender: Any, document: Document, change_type: str, **kwargs: Any
) -> None:
    """Email a document's subscribers when it changes (demo consumer)."""
    from . import subscriptions

    if not subscriptions.subscribers_of(document).exists():
        return
    _enqueue_notify(document.pk, change_type)


def _enqueue_notify(document_id: int, change_type: str) -> None:
    try:
        from .tasks import notify_subscribers_task

        notify_subscribers_task.enqueue(document_id, change_type)
    except Exception:
        from . import subscriptions

        subscriptions.send_update_notifications(document_id, change_type)


def _enqueue_prune(document_id: int) -> None:
    """Enqueue async pruning; fall back to inline if no task backend is present.

    The periodic ``run_retention`` sweep is the belt-and-suspenders backstop.
    """
    try:
        from .tasks import prune_versions_task

        prune_versions_task.enqueue(document_id)
    except Exception:
        from . import retention
        from .models import Document

        doc = Document.objects.filter(pk=document_id).first()
        if doc is not None:
            retention.prune_versions(doc)
