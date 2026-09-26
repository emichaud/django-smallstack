"""Loop guard (F-020): suppress_webhooks() stops outbound fan-out, inbound dispatch is
loop-safe by default, X-SmallStack-Origin is stamped, and ignore_origin drops self-events.

The runaway this prevents: an inbound handler (n8n-style) writes back into an
enable_webhooks model, which re-fires the outbound event, which the same n8n receives and
writes back again — 1→6 in the round-2 report.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest
from django.test import Client

from apps.webhooks import registry, services, suppress_webhooks, suppressed
from apps.webhooks.models import (
    WebhookDelivery,
    WebhookEndpoint,
    WebhookReceipt,
    WebhookReceiver,
)
from apps.webhooks.views import WebhookReceiverCRUDView

pytestmark = pytest.mark.django_db


@pytest.fixture
def receiver_emits_webhooks():
    original = WebhookReceiverCRUDView.enable_webhooks
    original_events = WebhookReceiverCRUDView.webhook_events
    WebhookReceiverCRUDView.enable_webhooks = True
    WebhookReceiverCRUDView.webhook_events = None
    try:
        yield
    finally:
        WebhookReceiverCRUDView.enable_webhooks = original
        WebhookReceiverCRUDView.webhook_events = original_events


@pytest.fixture(autouse=True)
def no_real_enqueue():
    with mock.patch("apps.webhooks.services._enqueue_delivery"):
        yield


@pytest.fixture(autouse=True)
def clean_handlers():
    registry.clear_handlers_for_tests()
    yield
    registry.clear_handlers_for_tests()


def _endpoint(patterns):
    return WebhookEndpoint.objects.create(
        name="e", target_url="https://hooks.example.com/x", event_filter=patterns
    )


# --- suppress_webhooks() -----------------------------------------------------


def test_suppressed_flag_tracks_context():
    assert suppressed() is False
    with suppress_webhooks():
        assert suppressed() is True
        with suppress_webhooks():  # re-entrant
            assert suppressed() is True
        assert suppressed() is True
    assert suppressed() is False


def test_suppress_webhooks_blocks_fan_out(receiver_emits_webhooks):
    _endpoint(["*"])
    with suppress_webhooks():
        WebhookReceiver.objects.create(name="R", slug="r")
    assert WebhookDelivery.objects.count() == 0


def test_write_outside_suppress_still_fires(receiver_emits_webhooks):
    _endpoint(["*"])
    WebhookReceiver.objects.create(name="R", slug="r")
    assert WebhookDelivery.objects.count() == 1


def test_suppress_restored_after_exception():
    with pytest.raises(ValueError):  # noqa: PT011
        with suppress_webhooks():
            raise ValueError("boom")
    assert suppressed() is False


# --- inbound dispatch is loop-safe by default --------------------------------


def _post(slug, body: bytes, sig, origin=None):
    headers = {}
    if sig is not None:
        # The receiver default is services.SIGNATURE_HEADER; the lookup is
        # case-insensitive (F-06).
        headers[services.SIGNATURE_HEADER] = sig
    if origin is not None:
        headers[services.ORIGIN_HEADER] = origin
    return Client().post(
        f"/webhooks/in/{slug}/", data=body, content_type="application/json", headers=headers
    )


def test_default_handler_write_back_does_not_run_away(receiver_emits_webhooks):
    """The flagship test: a handler that writes into an enable_webhooks model does NOT
    re-fire an outbound event (loop-safe by default)."""
    _endpoint(["*"])
    rec = WebhookReceiver.objects.create(name="In", slug="loop", secret="shh")

    @registry.webhook_handler("loop")
    def handle(receipt):
        # n8n-style write-back into a webhooks-enabled model.
        WebhookReceiver.objects.create(name="written-back", slug="wb")

    # Ignore any fan-out from the setup creates above; count only what dispatch fires.
    WebhookDelivery.objects.all().delete()

    body = json.dumps({"x": 1}).encode()
    resp = _post("loop", body, services.sign("shh", body))
    assert resp.status_code == 202
    rec_receipt = WebhookReceipt.objects.get(receiver=rec)
    assert rec_receipt.status == WebhookReceipt.Status.PROCESSED
    # The write-back happened...
    assert WebhookReceiver.objects.filter(slug="wb").exists()
    # ...but fired NO outbound delivery — the loop is broken.
    assert WebhookDelivery.objects.count() == 0


def test_cascade_handler_opts_out_of_loop_guard(receiver_emits_webhooks):
    _endpoint(["*"])
    WebhookReceiver.objects.create(name="In", slug="casc", secret="shh")

    @registry.webhook_handler("casc", cascade=True)
    def handle(receipt):
        WebhookReceiver.objects.create(name="cascaded", slug="cx")

    WebhookDelivery.objects.all().delete()
    body = b"{}"
    resp = _post("casc", body, services.sign("shh", body))
    assert resp.status_code == 202
    # cascade=True ⇒ the write-back DID fire an outbound delivery.
    assert WebhookDelivery.objects.count() == 1


# --- ignore_origin drops self-originated events ------------------------------


def test_ignore_origin_drops_self_event():
    rec = WebhookReceiver.objects.create(
        name="Paired", slug="paired", secret="shh", ignore_origin="https://me.example.com"
    )
    body = b"{}"
    resp = _post("paired", body, services.sign("shh", body), origin="https://me.example.com")
    assert resp.status_code == 202
    assert resp.json().get("ignored") is True
    receipt = WebhookReceipt.objects.get(receiver=rec)
    assert receipt.status == WebhookReceipt.Status.IGNORED
    assert receipt.origin == "https://me.example.com"


def test_ignore_origin_passes_foreign_event():
    rec = WebhookReceiver.objects.create(
        name="Paired", slug="paired", secret="shh", ignore_origin="https://me.example.com"
    )
    body = b"{}"

    @registry.webhook_handler("paired")
    def handle(receipt):
        pass

    resp = _post("paired", body, services.sign("shh", body), origin="https://other.example.com")
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get(receiver=rec)
    assert receipt.status == WebhookReceipt.Status.PROCESSED
    assert receipt.origin == "https://other.example.com"
