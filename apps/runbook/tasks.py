"""Background tasks for runbook (Django tasks / django-tasks-db)."""

from __future__ import annotations

from django.tasks import task

from . import retention
from .models import Document


@task()
def prune_versions_task(document_id: int) -> int:
    """Prune a document's superseded versions beyond its retention window."""
    doc = Document.objects.filter(pk=document_id).select_related("runbook").first()
    return retention.prune_versions(doc) if doc is not None else 0


@task()
def run_retention_sweep_task() -> dict[str, int]:
    """Full retention sweep (prune + expire) across all live documents."""
    return retention.run_sweep()


@task()
def notify_subscribers_task(document_id: int, change_type: str) -> int:
    """Email a document's subscribers about an update (async fan-out)."""
    from . import subscriptions

    return subscriptions.send_update_notifications(document_id, change_type)
