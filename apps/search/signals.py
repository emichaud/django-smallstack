"""Signal handlers that keep the search index current.

post_save / post_delete on any indexed model triggers an index write.
Lookup is O(1) via the registry. Handlers swallow exceptions because a
search index write should never break a model save — and each write runs
in its own ``transaction.atomic()`` block so that promise holds on
Postgres too: without the savepoint, a failed index write inside the
caller's transaction poisons it ("current transaction is aborted"), and
the *next* statement dies instead. SQLite shrugs a failed statement off,
which is exactly how this class of bug stays invisible in dev.

The ``view.model is not sender`` identity check exists for migrations:
``apps.get_model()`` hands RunPython a *historical* model class carrying
the same ``app_label.Name`` label the registry keys on, so the label
lookup matches — but indexing must not run there. The search column /
FTS table is provisioned by ``post_migrate`` (i.e. AFTER all migrations),
so on a from-scratch Postgres build the write hits a missing column
inside the migration's transaction and aborts the whole ``migrate``.
Migrations have no business maintaining the index; ``post_migrate``
provisions it and ``rebuild_search_index`` fills it.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("smallstack.search")


@receiver(post_save)
def _on_save(sender, instance, created, **kwargs):
    from .backends import get_backend
    from .registry import get_view

    view = get_view(sender)
    if view is None or view.model is not sender:
        return  # not indexed, or a historical model rendered by a migration
    try:
        with transaction.atomic():
            get_backend().index_object(view, instance)
    except Exception:
        logger.exception("Search index update failed for %s pk=%s", view.model_label, instance.pk)


@receiver(post_delete)
def _on_delete(sender, instance, **kwargs):
    from .backends import get_backend
    from .registry import get_view

    view = get_view(sender)
    if view is None or view.model is not sender:
        return
    try:
        with transaction.atomic():
            get_backend().remove_object(view, instance.pk)
    except Exception:
        logger.exception(
            "Search index delete failed for %s pk=%s", view.model_label, instance.pk
        )
