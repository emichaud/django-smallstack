"""The Blog tile on the central /smallstack/ dashboard.

Its one non-obvious job: turn *degraded* on the two failures that are
otherwise silent — a scheduled post past its time, or an issue stuck mid-send.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.blog.dashboard_widgets import BlogDashboardWidget
from apps.blog.models import Issue, Post

pytestmark = pytest.mark.django_db


def test_it_is_registered_as_a_standalone_widget():
    from apps.smallstack import dashboard

    titles = [w.title for w in dashboard.get_standalone_widgets()]
    assert "Blog" in titles


def test_empty_state_invites_rather_than_alarms(db):
    data = BlogDashboardWidget().get_data()
    assert data["headline"] == "No blogs yet"
    assert data["status"] == "operational"


def test_counts_live_drafts_and_scheduled(blog, post, draft, scheduled_post, future_published_post):
    data = BlogDashboardWidget().get_data()
    assert data["headline"] == "1 live post", "an embargoed post is not live"
    assert "1 draft" in data["detail"]
    assert "1 scheduled" in data["detail"]
    assert "across 1 blog" in data["detail"]
    assert data["status"] == "operational"


def test_an_overdue_scheduled_post_turns_it_degraded(blog, owner):
    Post.objects.create(
        blog=blog, title="Late", slug="late", author=owner, status=Post.Status.SCHEDULED,
        scheduled_for=timezone.now() - timezone.timedelta(hours=1),
    )
    data = BlogDashboardWidget().get_data()
    assert data["status"] == "degraded"
    assert "overdue" in data["detail"]


def test_a_stalled_send_turns_it_degraded(blog):
    Issue.objects.create(
        blog=blog, subject="Stuck", status=Issue.Status.SENDING,
        started_at=timezone.now() - timezone.timedelta(hours=2),
    )
    data = BlogDashboardWidget().get_data()
    assert data["status"] == "degraded"
    assert "stalled" in data["detail"]


def test_api_extras_never_include_an_address(blog, confirmed_sub, subscriber):
    extras = BlogDashboardWidget().get_api_extras()
    assert extras["confirmed_subscribers"] == 1
    assert subscriber.email not in str(extras)


def test_it_renders_on_the_dashboard_for_staff(client, staff, blog, post):
    client.force_login(staff)
    body = client.get("/smallstack/").content.decode()
    assert "1 live post" in body
    assert 'href="/smallstack/blog/posts/"' in body
