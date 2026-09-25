"""Reliability reshape: stable event_id (F-021), Retry-After honoring (F-022), and bulk
dead-letter replay (F-023)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.webhooks import services
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint
from apps.webhooks.tasks import _record_attempt

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_real_enqueue():
    with mock.patch("apps.webhooks.services._enqueue_delivery") as m:
        yield m


def _endpoint():
    return WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")


def _dead(endpoint, event_id=None, created=None):
    d = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_type="t.t.created",
        payload={"data": {"id": 1}},
        event_id=event_id,
        status=WebhookDelivery.Status.DEAD,
        max_attempts=3,
    )
    if created is not None:
        WebhookDelivery.objects.filter(pk=d.pk).update(created_at=created)
        d.refresh_from_db()
    return d


# --- F-021 stable event_id ---------------------------------------------------


def test_replay_reuses_event_id():
    ep = _endpoint()
    eid = uuid.uuid4()
    original = _dead(ep, event_id=eid)
    replay = services.replay_delivery(original)
    assert replay.pk != original.pk
    assert replay.event_id == original.event_id == eid


def test_event_id_header_sent(monkeypatch):
    """deliver_webhook stamps X-SmallStack-Event-Id when the delivery has one."""
    ep = _endpoint()
    eid = uuid.uuid4()
    d = WebhookDelivery.objects.create(
        endpoint=ep, event_type="t.t.created", payload={"x": 1}, event_id=eid
    )
    captured = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["headers"] = req.headers
        return FakeResp()

    monkeypatch.setattr("apps.webhooks.tasks._open", fake_urlopen)
    from apps.webhooks.tasks import deliver_webhook

    deliver_webhook.func(d.pk)
    # urllib title-cases header keys.
    assert captured["headers"].get("X-smallstack-event-id") == str(eid)
    assert captured["headers"].get("X-smallstack-origin")


# --- F-022 Retry-After -------------------------------------------------------


def test_retry_after_overrides_backoff():
    ep = _endpoint()
    d = WebhookDelivery.objects.create(
        endpoint=ep, event_type="t", payload={}, max_attempts=5, attempt=0
    )
    before = timezone.now()
    # Fixed backoff table would give 60s for attempt 1; Retry-After says 5s.
    with mock.patch.object(services, "backoff_seconds", return_value=60):
        _record_attempt(d, attempt=1, status_code=429, elapsed_ms=1, error="", succeeded=False, retry_after=5)
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.RETRYING
    wait = (d.next_attempt_at - before).total_seconds()
    assert 4 <= wait <= 8  # ~5s, not 60s


def test_retry_after_clamped_to_max():
    ep = _endpoint()
    d = WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={}, max_attempts=5)
    before = timezone.now()
    with mock.patch.object(services, "max_backoff", return_value=30):
        _record_attempt(d, attempt=1, status_code=503, elapsed_ms=1, error="", succeeded=False, retry_after=99999)
    d.refresh_from_db()
    wait = (d.next_attempt_at - before).total_seconds()
    assert wait <= 32  # clamped to 30s ceiling


def test_parse_retry_after_variants():
    assert services.parse_retry_after("5") == 5
    assert services.parse_retry_after(None) is None
    assert services.parse_retry_after("not-a-date") is None
    # HTTP-date in the past clamps to 0.
    assert services.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0
    # A near-future HTTP-date gives a positive delta.
    future = (timezone.now() + timedelta(seconds=120)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    val = services.parse_retry_after(future)
    assert val is not None and 60 <= val <= 130


# --- F-023 bulk dead-letter replay -------------------------------------------


def test_replay_dead_all(no_real_enqueue):
    ep = _endpoint()
    _dead(ep, event_id=uuid.uuid4())
    _dead(ep, event_id=uuid.uuid4())
    # A non-dead delivery is NOT replayed.
    WebhookDelivery.objects.create(
        endpoint=ep, event_type="t", payload={}, status=WebhookDelivery.Status.SUCCESS
    )
    new_ids = services.replay_dead()
    assert len(new_ids) == 2
    # Each replay reused its original's event_id (2 distinct originals ⇒ 2 event_ids).
    replays = WebhookDelivery.objects.filter(pk__in=new_ids)
    assert replays.exclude(event_id__isnull=True).count() == 2


def test_replay_dead_scoped_to_endpoint():
    ep1, ep2 = _endpoint(), _endpoint()
    _dead(ep1)
    _dead(ep2)
    new_ids = services.replay_dead(endpoint_id=ep1.pk)
    assert len(new_ids) == 1
    assert WebhookDelivery.objects.get(pk=new_ids[0]).endpoint_id == ep1.pk


def test_replay_dead_since_filter():
    ep = _endpoint()
    old = timezone.now() - timedelta(days=2)
    _dead(ep, created=old)
    _dead(ep)  # recent
    new_ids = services.replay_dead(since=timezone.now() - timedelta(hours=1))
    assert len(new_ids) == 1
