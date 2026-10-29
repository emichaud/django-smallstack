"""The board on the pages that adopted it: blog posts/issues and runbook documents."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone as dt_tz

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="adopt-staff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def _aware(y: int, m: int, d: int, h: int = 12) -> datetime:
    return datetime(y, m, d, h, tzinfo=dt_tz.utc)


def test_blog_posts_and_issues_offer_the_board(client, staff):
    from apps.blog import service
    from apps.blog.models import Issue

    blog = service.create_blog(name="Board blog", owner=staff, slug="board-blog", actor=staff)
    post = service.create_post(blog, title="Board post", body_markdown="x", actor=staff)
    service.publish_post(post, at=_aware(2026, 4, 3), actor=staff)
    Issue.objects.create(blog=blog, subject="April issue", status=Issue.Status.SENT, started_at=_aware(2026, 4, 2),
                         finished_at=_aware(2026, 4, 2, 13), created_by=staff)

    params = {"display": "board", "range": "30", "from": "2026-04-01", "day": "2026-04-03"}
    resp = client.get(reverse("blog/posts-list"), params)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-display="board"' in html and 'data-display="calendar"' in html
    assert "Board post" in html and "cal-bcard--success" in html and "Board blog" in html
    assert 'cal-day-group-title">Posts' in html or 'cal-day-group-title">Blog posts' in html

    # Issues are history: the board ends on the anchor (the last 30 days).
    resp = client.get(reverse("blog/issues-list"), {"display": "board", "range": "30", "from": "2026-04-10"})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "April issue" in html and "12 Mar – 10 Apr 2026" in html


def test_runbook_documents_board(client, staff):
    from apps.runbook.models import Document, Runbook, Section

    rb = Runbook.objects.create(name="Ops", slug="ops", owner=staff)
    sec = Section.objects.create(runbook=rb, name="Core", slug="core")
    doc = Document.objects.create(runbook=rb, section=sec, title="Restart the queue", key="restart", slug="restart",
                                  created_by=staff)
    Document.objects.filter(pk=doc.pk).update(updated_at=_aware(2026, 4, 3))

    url = reverse("runbook:document_list")
    resp = client.get(url)
    assert resp.status_code == 200 and resp.context["board_mode"] is False
    assert "?view=board" in resp.content.decode()

    resp = client.get(url, {"view": "board", "range": "30", "from": "2026-04-10", "day": "2026-04-03"})
    assert resp.status_code == 200 and resp.context["board_mode"] is True
    html = resp.content.decode()
    assert "Restart the queue" in html and "Ops" in html
    assert "12 Mar – 10 Apr 2026" in html and "Friday, April 3" in html
    assert 'cal-day-group-title">Documents' in html
    # Search narrows the board too, and the form keeps the board state.
    resp = client.get(url, {"view": "board", "range": "30", "from": "2026-04-10", "q": "nomatch"})
    assert resp.context["event_count"] == 0
    assert 'name="view" value="board"' in resp.content.decode()
