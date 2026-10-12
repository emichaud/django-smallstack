"""Status monitors for the blog's background work.

Both scheduled jobs here are silent failures by nature: with no
``manage.py db_worker`` running, scheduled posts simply never go live and a
queued newsletter simply never sends. Nothing errors, nothing logs, and the
author just finds out later from a reader. These monitors are what make that
visible on ``/smallstack/status/``.
"""

from __future__ import annotations

from apps.smallstack.monitors import CheckResult, Monitor, Service


class BlogService(Service):
    key = "blog"
    name = "Blog"
    description = "Scheduled publishing and newsletter delivery."


class ScheduledPostsMonitor(Monitor):
    """Overdue scheduled posts mean the publisher tick is not running."""

    key = "blog-scheduled-posts"
    name = "Scheduled posts"
    service_key = "blog"
    description = "Posts past their publish time that are still waiting."

    def check(self) -> CheckResult:
        from . import service

        overdue = service.due_post_count()
        if overdue == 0:
            return CheckResult.up(note="No posts are overdue.")
        return CheckResult.down(
            f"{overdue} scheduled post(s) are past their publish time. "
            "Is `manage.py db_worker` running?"
        )


class NewsletterSendMonitor(Monitor):
    """An issue stuck in `sending` means the email queue is not draining."""

    key = "blog-newsletter-send"
    name = "Newsletter delivery"
    service_key = "blog"
    description = "Issues that started sending but never finished."

    def check(self) -> CheckResult:
        from . import service

        stuck = service.due_issue_count()
        if stuck == 0:
            return CheckResult.up(note="No sends are stalled.")
        return CheckResult.down(
            f"{stuck} newsletter issue(s) have been sending for over an hour. "
            "Check that a worker is draining the `email` queue."
        )


class AutoSyncMonitor(Monitor):
    """Auto-synced posts drifting behind their runbook document.

    `sync="auto"` is honoured by *enqueuing* a resync from the
    `document_written` receiver, not by syncing inline — so with no worker on
    the default queue the post keeps serving yesterday's text and nothing says
    so. The other two monitors here cover the scheduled jobs; this covers the
    on-demand one, which was the only silent-failure path in the app with no
    signal at all.
    """

    key = "blog-auto-sync"
    name = "Runbook auto-sync"
    service_key = "blog"
    description = "Auto-synced posts whose source document has moved on."

    def check(self) -> CheckResult:
        from . import service

        stale = service.stale_autosync_count()
        if stale == 0:
            return CheckResult.up(note="All auto-synced posts are current.")
        return CheckResult.down(
            f"{stale} auto-synced post(s) are behind their runbook document. "
            "Is `manage.py db_worker` running on the default queue?"
        )
