"""Blog widget for the central /smallstack/ dashboard.

Sits beside Runbook. Cheap — a handful of aggregate counts — and it goes
*degraded* on the two conditions that otherwise fail silently: a scheduled post
past its time, or a newsletter issue stuck mid-send. Both mean no worker is
draining a queue, which nothing else on the dashboard would show.
"""

from __future__ import annotations

from typing import Any

from apps.smallstack.displays import DashboardWidget


class BlogDashboardWidget(DashboardWidget):
    title = "Blog"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z'
        'm-2 4H7V5h10v2zm0 4H7V9h10v2zm-3 4H7v-2h7v2z"/></svg>'
    )
    order = 34  # after Runbook (32) and Search (33), before MCP (35)
    url_name = "blog/posts-list"  # the system manager; this dashboard is staff-only

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from django.db.models import Count, Q
        from django.utils import timezone

        from . import service
        from .models import Blog, Post

        blogs = Blog.objects.count()
        if blogs == 0:
            return {
                "headline": "No blogs yet",
                "detail": "Anyone signed in can start one under My blogs",
                "status": "operational",
            }

        now = timezone.now()
        counts = Post.objects.aggregate(
            live=Count("pk", filter=Q(status=Post.Status.PUBLISHED, published_at__lte=now)),
            drafts=Count("pk", filter=Q(status=Post.Status.DRAFT)),
            scheduled=Count("pk", filter=Q(status=Post.Status.SCHEDULED)),
        )
        overdue = service.due_post_count(now_=now)
        stuck = service.due_issue_count(now_=now)

        live = counts["live"] or 0
        headline = f"{live} live post{'' if live == 1 else 's'}"
        parts = []
        if counts["drafts"]:
            parts.append(f"{counts['drafts']} draft{'' if counts['drafts'] == 1 else 's'}")
        if counts["scheduled"]:
            parts.append(f"{counts['scheduled']} scheduled")
        detail = (", ".join(parts) + " " if parts else "") + f"across {blogs} blog{'' if blogs == 1 else 's'}"

        status = "operational"
        if overdue:
            status = "degraded"
            detail = f"{overdue} scheduled post{'' if overdue == 1 else 's'} overdue — is a worker running?"
        elif stuck:
            status = "degraded"
            detail = f"{stuck} newsletter send{'' if stuck == 1 else 's'} stalled — check the email queue"

        return {"headline": headline, "detail": detail, "status": status}

    def get_api_extras(self, model_class: type | None = None) -> dict[str, Any] | None:
        from django.db.models import Count

        from .models import Blog, Issue, Post, Subscription

        by_status = dict(Post.objects.values_list("status").annotate(n=Count("pk")))
        by_visibility = dict(Blog.objects.values_list("visibility").annotate(n=Count("pk")))
        return {
            "blogs": Blog.objects.count(),
            "blogs_by_visibility": {k: by_visibility.get(k, 0) for k in Blog.Visibility.values},
            "posts_by_status": {k: by_status.get(k, 0) for k in Post.Status.values},
            "confirmed_subscribers": Subscription.objects.filter(
                status=Subscription.Status.CONFIRMED
            ).count(),
            "issues_sent": Issue.objects.filter(status=Issue.Status.SENT).count(),
        }
