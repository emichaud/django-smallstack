"""Retention & lifecycle for documents.

Two independent axes, both scoped so machine docs are strict and human docs are
untouched by default:

  * **version retention** — bound the *history* of a persistent doc
    (``max_versions`` / ``max_version_age_days``); prune superseded versions,
    never the head, never the images (which live on the Document).
  * **document TTL** — the *whole doc* self-cleans (``ttl_days`` after last
    update; ``on_expire`` = archive | delete).

Effective policy resolves: document override → runbook default → global default
keyed by ``is_generated`` (see ``conf``). The janitor (``run_sweep``) is driven
by a periodic management command; version pruning is additionally enqueued on
write via the ``document_written`` event.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

from . import conf, signals
from .models import Document, DocumentVersion


@dataclasses.dataclass(frozen=True)
class RetentionPolicy:
    max_versions: Optional[int]
    max_version_age_days: Optional[int]
    ttl_days: Optional[int]
    on_expire: str  # "archive" | "delete"


def effective_policy(doc: Document) -> RetentionPolicy:
    """Resolve doc override → runbook default → global default (by is_generated)."""
    rb = doc.runbook
    gen = doc.is_generated

    def resolve(doc_field: str, rb_field: str, global_value: Optional[int]) -> Optional[int]:
        value = getattr(doc, doc_field)
        if value is not None:
            return value
        if rb is not None:
            rb_value = getattr(rb, rb_field)
            if rb_value is not None:
                return rb_value
        return global_value

    return RetentionPolicy(
        max_versions=resolve("max_versions", "default_max_versions", conf.global_max_versions(gen)),
        max_version_age_days=resolve(
            "max_version_age_days", "default_max_version_age_days", conf.global_max_version_age_days(gen)
        ),
        ttl_days=resolve("ttl_days", "default_ttl_days", conf.global_ttl_days(gen)),
        on_expire=doc.on_expire or "archive",
    )


def prune_versions(doc: Document) -> int:
    """Delete superseded versions beyond the policy window. Never touches the
    current head (or images, which hang off the Document). Returns the count."""
    policy = effective_policy(doc)
    if policy.max_versions is None and policy.max_version_age_days is None:
        return 0

    versions = list(doc.versions.order_by("-version"))  # newest first
    doomed: set[int] = set()

    if policy.max_versions is not None:
        for version in versions[policy.max_versions:]:
            doomed.add(version.pk)

    if policy.max_version_age_days is not None:
        cutoff = timezone.now() - timedelta(days=policy.max_version_age_days)
        for version in versions:
            if version.created_at < cutoff:
                doomed.add(version.pk)

    doomed.discard(doc.current_version_id)  # never the head
    if not doomed:
        return 0
    return DocumentVersion.objects.filter(pk__in=doomed).delete()[0]


def is_expired(doc: Document, now: Optional[datetime] = None) -> bool:
    """True when a TTL is set and the doc has been idle past it (and not archived)."""
    policy = effective_policy(doc)
    if policy.ttl_days is None or doc.is_archived:
        return False
    now = now or timezone.now()
    return doc.updated_at < now - timedelta(days=policy.ttl_days)


def expire_document(doc: Document) -> str:
    """Apply the doc's expiry action (archive|delete) and emit ``document_expired``.

    Returns the action taken.
    """
    policy = effective_policy(doc)

    def _emit() -> None:
        signals.document_expired.send(sender=Document, document=doc, policy=policy)

    transaction.on_commit(_emit)

    if policy.on_expire == "delete":
        doc.delete()
    else:
        doc.is_archived = True
        doc.archived_at = timezone.now()
        doc.save(update_fields=["is_archived", "archived_at", "updated_at"])
    return policy.on_expire


def run_sweep(now: Optional[datetime] = None) -> dict[str, int]:
    """Prune versions and expire idle documents across all live documents.

    Idempotent; safe to run on a schedule. Returns counts.
    """
    now = now or timezone.now()
    pruned_versions = 0
    expired_documents = 0

    for doc in Document.objects.filter(is_archived=False).select_related("runbook").iterator():
        pruned_versions += prune_versions(doc)
        if is_expired(doc, now):
            expire_document(doc)
            expired_documents += 1

    return {"pruned_versions": pruned_versions, "expired_documents": expired_documents}
