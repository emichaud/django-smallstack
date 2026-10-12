"""React to runbook writes.

``document_written`` is runbook's public event seam — emitted on
``transaction.on_commit`` with the document, its new version and the actor.
Posts published from a document with ``source_sync="auto"`` follow it; posts
set to ``manual`` are deliberately left alone, so an author who published a
page once and then edited the post does not have those edits silently
overwritten the next time someone touches the runbook.

Connected from ``BlogConfig.ready()``. Everything here is best-effort: a
failure to resync a blog post must never break the runbook write that caused
it.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver

logger = logging.getLogger("smallstack.blog")


def connect() -> None:
    """Wire the receivers. Called from ``BlogConfig.ready()``.

    A function rather than import-time side effects so the AppConfig can wrap
    it in its own try/except, and so a project that does not install runbook
    simply gets an ImportError it can ignore.
    """
    from apps.runbook.signals import document_written

    @receiver(document_written, dispatch_uid="blog_resync_on_document_written")
    def _resync_published_posts(sender: Any, **kwargs: Any) -> None:
        document = kwargs.get("document")
        if document is None:
            return
        try:
            from .models import Post
            from .tasks import enqueue_resync

            post_ids = list(
                Post.objects.filter(
                    source_document=document, source_sync="auto"
                ).values_list("pk", flat=True)
            )
            for post_id in post_ids:
                enqueue_resync(post_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "blog: failed to resync posts for runbook document %s",
                getattr(document, "pk", "?"),
            )
