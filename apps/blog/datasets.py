"""Bundled datasets for blogs + newsletters: posts, subscriptions, issues, deliveries.

Post bodies and subscriber email addresses are not columns; a subscriber is
referenced by foreign key only.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.calendar import register_calendar
from apps.datasets.framework import framework_dataset

from .models import Delivery, Issue, Post, Subscription


@framework_dataset(
    "smallstack_blog_posts",
    label="Blog posts",
    description=(
        "Every post across all blogs: blog, author, status, publish/schedule dates, featured and newsletter flags."
    ),
    columns=[
        "blog",
        "author",
        "title",
        "slug",
        "status",
        "published_at",
        "scheduled_for",
        "is_featured",
        "allow_newsletter",
        "source_document",
        "created_at",
        "updated_at",
    ],
    filterable=[
        "blog",
        "author",
        "status",
        "published_at",
        "scheduled_for",
        "is_featured",
        "allow_newsletter",
        "created_at",
    ],
)
def blog_posts() -> QuerySet[Post]:
    return Post.objects.select_related("blog", "author")


@framework_dataset(
    "smallstack_blog_subscriptions",
    label="Newsletter subscriptions",
    description=(
        "One row per subscriber-to-blog subscription: status, how it was acquired, and the "
        "confirm/unsubscribe timeline."
    ),
    columns=["blog", "subscriber", "status", "source", "confirmed_at", "unsubscribed_at", "created_at"],
    filterable=["blog", "status", "source", "confirmed_at", "unsubscribed_at", "created_at"],
)
def blog_subscriptions() -> QuerySet[Subscription]:
    return Subscription.objects.select_related("blog", "subscriber")


@framework_dataset(
    "smallstack_blog_issues",
    label="Newsletter issues",
    description=(
        "Every newsletter send: blog, post, status, timeline and recipient/sent/failed counts. sent_pct "
        "and failed_pct roll up correctly across issues."
    ),
    columns=[
        "blog",
        "post",
        "subject",
        "status",
        "scheduled_for",
        "queued_at",
        "started_at",
        "finished_at",
        "recipient_count",
        "sent_count",
        "failed_count",
        "created_by",
        "created_at",
    ],
    filterable=["blog", "status", "scheduled_for", "started_at", "finished_at", "created_by", "created_at"],
    measures=[
        ("sent_pct", "sent_count", "recipient_count", "percent"),
        ("failed_pct", "failed_count", "recipient_count", "percent"),
    ],
)
def blog_issues() -> QuerySet[Issue]:
    return Issue.objects.select_related("blog", "post")


@framework_dataset(
    "smallstack_blog_deliveries",
    label="Newsletter deliveries",
    description=(
        "One row per recipient per issue: delivery status, attempts, when it was sent and the last error if any."
    ),
    columns=["issue", "subscriber", "status", "attempts", "claimed_at", "sent_at", "last_error"],
    filterable=["issue", "status", "attempts", "sent_at"],
)
def blog_deliveries() -> QuerySet[Delivery]:
    return Delivery.objects.select_related("issue", "subscriber")


# ---------------------------------------------------------------------------
# Calendar protocol
# ---------------------------------------------------------------------------

register_calendar(
    "smallstack_blog_posts",
    start="published_at",
    title="title",
    subtitle=lambda p: p.blog.name,
    status=lambda p: {Post.Status.PUBLISHED: "success", Post.Status.SCHEDULED: "warning"}.get(p.status),
    label="Blog posts",
    description="Posts on their publish date, across every blog.",
)

register_calendar(
    "smallstack_blog_issues",
    start="started_at",
    title="subject",
    subtitle=lambda i: i.blog.name,
    status=lambda i: {Issue.Status.SENT: "success", Issue.Status.FAILED: "danger"}.get(i.status),
    label="Newsletter sends",
    description="Newsletter issues on the day their send began, tinted by outcome.",
)
