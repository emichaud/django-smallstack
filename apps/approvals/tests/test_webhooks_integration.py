"""enable_webhooks integration — decisions are observable from outside.

The remote-consumer story the skill doc sells: subscribe to
``smallstack_approvals.approvalrequest.updated`` and read ``data.status``.
These tests prove the global post_save tap actually emits for this model and
that the payload carries the decision.
"""

from __future__ import annotations

import pytest

from apps.approvals import services
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint

pytestmark = pytest.mark.django_db

EVENT_PREFIX = "smallstack_approvals.approvalrequest"


@pytest.fixture
def endpoint(db):
    return WebhookEndpoint.objects.create(
        name="consumer",
        target_url="https://consumer.example/hook",
        secret="s3cret",
        event_filter=[f"{EVENT_PREFIX}.*"],
    )


def _file(actor, **kwargs):
    defaults = {"kind": "test.sample", "title": "Do the thing"}
    defaults.update(kwargs)
    return services.request_approval(actor=actor, **defaults)


def test_filing_emits_created_event(endpoint, requester, sample_kind):
    req = _file(requester)
    delivery = WebhookDelivery.objects.get(event_type=f"{EVENT_PREFIX}.created")
    assert delivery.endpoint == endpoint
    assert delivery.payload["data"]["status"] == "pending"
    assert delivery.payload["data"]["id"] == req.pk


def test_decision_rides_updated_with_status(endpoint, requester, staff, sample_kind):
    req = _file(requester)
    services.approve(req, actor=staff, note="ok")
    updates = WebhookDelivery.objects.filter(event_type=f"{EVENT_PREFIX}.updated")
    assert updates.exists()
    payload = updates.latest("id").payload
    assert payload["data"]["status"] == "approved"
    assert payload["data"]["decision_note"] == "ok"
    assert payload["resource"]["id"] == req.pk


def test_expiry_also_emits_updated(endpoint, requester, sample_kind):
    from datetime import timedelta

    from django.utils import timezone

    _file(requester, expires_at=timezone.now() - timedelta(minutes=1))
    assert services.mark_expired() == 1
    payload = (
        WebhookDelivery.objects.filter(event_type=f"{EVENT_PREFIX}.updated").latest("id").payload
    )
    assert payload["data"]["status"] == "expired"


def test_no_delivery_without_matching_subscription(requester, sample_kind):
    WebhookEndpoint.objects.create(
        name="other", target_url="https://x.example/", secret="s",
        event_filter=["scheduler.scheduledjob.*"],
    )
    _file(requester)
    assert not WebhookDelivery.objects.filter(event_type__startswith=EVENT_PREFIX).exists()
