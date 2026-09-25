"""deliver_webhook: success, retry scheduling, and give-up (dead) paths.

urlopen is patched so no real HTTP happens; the endpoint URL is loopback with
ALLOW_PRIVATE so the SSRF guard passes at send time.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

import pytest
from django.utils import timezone

from apps.webhooks.models import WebhookDelivery, WebhookEndpoint
from apps.webhooks.tasks import deliver_webhook

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def allow_private(settings):
    """Loopback target URLs must pass the SSRF guard in these tests."""
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = True


@contextmanager
def fake_response(status: int):
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__.return_value = resp
    with mock.patch("apps.webhooks.tasks._open", return_value=resp) as m:
        yield m


@contextmanager
def fake_error(exc: Exception):
    with mock.patch("apps.webhooks.tasks._open", side_effect=exc) as m:
        yield m


def _delivery(max_attempts=5):
    ep = WebhookEndpoint.objects.create(
        name="e", target_url="http://127.0.0.1:9000/hook", event_filter=["*"]
    )
    return WebhookDelivery.objects.create(
        endpoint=ep, event_type="t.t.created", payload={"x": 1}, max_attempts=max_attempts
    )


def test_success_marks_delivery_and_endpoint():
    d = _delivery()
    with fake_response(200):
        result = deliver_webhook.func(d.pk)
    assert result["success"] is True
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.SUCCESS
    assert d.response_status == 200
    assert d.next_attempt_at is None
    d.endpoint.refresh_from_db()
    assert d.endpoint.total_deliveries == 1
    assert d.endpoint.consecutive_failures == 0
    assert d.endpoint.last_status == WebhookEndpoint.Status.SUCCESS


def test_signature_header_is_sent():
    d = _delivery()
    with fake_response(200) as m:
        deliver_webhook.func(d.pk)
    req = m.call_args.args[0]
    assert req.headers  # urllib normalizes header keys to Capitalized
    assert any(k.lower() == "x-smallstack-signature" for k in req.headers)
    assert any(k.lower() == "x-smallstack-event" for k in req.headers)


def test_failure_schedules_retry():
    d = _delivery(max_attempts=5)
    with fake_error(OSError("connection refused")):
        deliver_webhook.func(d.pk)
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.RETRYING
    assert d.attempt == 1
    assert d.next_attempt_at is not None
    assert d.next_attempt_at > timezone.now()


def test_http_5xx_is_a_failure():
    d = _delivery(max_attempts=5)
    with fake_response(503):
        deliver_webhook.func(d.pk)
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.RETRYING
    assert d.response_status == 503


def test_exhausted_retries_marks_dead():
    d = _delivery(max_attempts=1)
    with fake_error(OSError("nope")):
        deliver_webhook.func(d.pk)
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.DEAD
    assert d.next_attempt_at is None
    d.endpoint.refresh_from_db()
    assert d.endpoint.last_status == WebhookEndpoint.Status.DEAD


def test_ssrf_guard_blocks_at_send_time(settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = False  # override the autouse fixture
    d = _delivery(max_attempts=1)
    # No urlopen patch needed — the guard should short-circuit before any HTTP.
    deliver_webhook.func(d.pk)
    d.refresh_from_db()
    assert d.status == WebhookDelivery.Status.DEAD
    assert "SSRF" in d.error or "private" in d.error.lower()
