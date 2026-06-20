"""Signal handlers that keep the search index current.

post_save / post_delete on any indexed model triggers an index write.
Lookup is O(1) via the registry. Handlers swallow exceptions because a
search index write should never break a model save.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("smallstack.search")


@receiver(post_save)
def _on_save(sender, instance, created, **kwargs):
    from .backends import get_backend
    from .registry import get_view

    view = get_view(sender)
    if view is None:
        return
    try:
        get_backend().index_object(view, instance)
    except Exception:
        logger.exception("Search index update failed for %s pk=%s", view.model_label, instance.pk)


@receiver(post_delete)
def _on_delete(sender, instance, **kwargs):
    from .backends import get_backend
    from .registry import get_view

    view = get_view(sender)
    if view is None:
        return
    try:
        get_backend().remove_object(view, instance.pk)
    except Exception:
        logger.exception(
            "Search index delete failed for %s pk=%s", view.model_label, instance.pk
        )
