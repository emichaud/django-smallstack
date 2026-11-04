"""The delivery detail page: one line of the send ledger, read as a receipt.

The outcome in a sentence, the three moments in order, the error in full,
and links to the issue, the blog and (for staff) the subscriber record.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.blog.models import Delivery

pytestmark = pytest.mark.django_db

CONSOLE = "/smallstack/blog"


def _page(client, delivery: Delivery) -> str:
    resp = client.get(f"{CONSOLE}/deliveries/{delivery.pk}/")
    assert resp.status_code == 200
    return resp.content.decode()


def test_a_sent_copy_reads_as_a_receipt(client, owner, issue, subscriber):
    now = timezone.now()
    issue.queued_at = now
    issue.save(update_fields=["queued_at"])
    d = Delivery.objects.create(
        issue=issue,
        subscriber=subscriber,
        email=subscriber.email,
        status=Delivery.Status.SENT,
        attempts=1,
        claimed_at=now,
        sent_at=now,
    )
    client.force_login(owner)
    html = _page(client, d)
    assert "The mail server accepted this copy on the first attempt." in html
    assert 'class="dl-status">Sent<' in html
    # Three steps, all reached.
    assert html.count("dl-step--done") == 3 and "dl-step--todo" not in html
    # The framework field table is gone; the facts link onward instead.
    assert "<th" not in html.split('class="card dl-card"')[1]
    assert f'href="{CONSOLE}/issues/{issue.pk}/"' in html
    assert f'href="{CONSOLE}/blogs/{issue.blog_id}/"' in html
    assert f'href="{CONSOLE}/deliveries/?issue={issue.pk}"' in html
    assert "Issue 1" in html and "Field Notes" in html
    assert "of up to 3" in html
    # The breadcrumb spells the plural properly, here and on the list.
    assert "Deliveries" in html and "Deliverys" not in html
    listing = client.get(f"{CONSOLE}/deliveries/").content.decode()
    assert "Deliveries" in listing and "Deliverys" not in listing
    # The owner is not staff: no link to the subscriber record, which 403s for them.
    assert f"{CONSOLE}/subscribers/" not in html
    assert "Reader" in html


def test_a_failed_copy_shows_the_whole_error_and_why(client, owner, issue, subscriber):
    error = "SMTPServerDisconnected: Connection unexpectedly closed " + "x" * 300
    d = Delivery.objects.create(
        issue=issue,
        subscriber=subscriber,
        email=subscriber.email,
        status=Delivery.Status.FAILED,
        attempts=3,
        last_error=error,
    )
    client.force_login(owner)
    html = _page(client, d)
    assert "Gave up after 3 attempts, each one a temporary error." in html
    assert error in html  # the list previews it; the page shows all of it
    assert "dl-step--error" in html and "After 3 attempts" in html
    # Fewer attempts than the limit means the server rejected the address outright.
    d.attempts = 1
    d.save(update_fields=["attempts"])
    html = _page(client, d)
    assert "rejected the address outright" in html


def test_pending_claimed_and_skipped_say_what_happens_next(client, owner, issue, subscriber):
    d = Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    client.force_login(owner)
    html = _page(client, d)
    assert "Waiting in the queue for the next send tick." in html
    assert "Waiting for a worker" in html and "Not yet" in html
    d.attempts = 2
    d.save(update_fields=["attempts"])
    assert "Back in the queue: 2 of 3 attempts hit a temporary error." in _page(client, d)
    d.status, d.claimed_at = Delivery.Status.CLAIMED, timezone.now()
    d.save(update_fields=["status", "claimed_at"])
    html = _page(client, d)
    assert "A worker is sending it now." in html and 'aria-current="step"' in html
    d.status = Delivery.Status.SKIPPED
    d.save(update_fields=["status"])
    html = _page(client, d)
    assert "Not sent. The reader unsubscribed, or the send was stopped," in html
    assert "Never attempted" in html


def test_staff_get_the_subscriber_link_and_a_removed_record_is_said_so(client, issue, subscriber):
    staff = get_user_model().objects.create_user(username="staff", password="pw", is_staff=True)
    client.force_login(staff)
    d = Delivery.objects.create(issue=issue, subscriber=subscriber, email=subscriber.email)
    html = _page(client, d)
    assert f'href="{CONSOLE}/subscribers/{subscriber.pk}/"' in html
    d.subscriber = None
    d.save(update_fields=["subscriber"])
    html = _page(client, d)
    assert f"{CONSOLE}/subscribers/" not in html
    assert "Record removed." in html and subscriber.email in html
