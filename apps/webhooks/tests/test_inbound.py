"""Inbound receiver view: signature verify, receipt logging, handler dispatch.

Tasks run immediately in tests (ImmediateBackend), so dispatch_incoming runs the
registered handler synchronously during the POST — letting us assert PROCESSED.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.webhooks import registry, services
from apps.webhooks.models import WebhookReceipt, WebhookReceiver

pytestmark = pytest.mark.django_db

HANDLED: list = []


@pytest.fixture(autouse=True)
def clean_handlers():
    registry.clear_handlers_for_tests()
    HANDLED.clear()
    yield
    registry.clear_handlers_for_tests()
    HANDLED.clear()


@pytest.fixture
def receiver():
    return WebhookReceiver.objects.create(name="Stripe", slug="stripe", secret="shh")


def _post(client, slug, body: bytes, sig: str | None):
    headers = {}
    if sig is not None:
        headers["X-Signature"] = sig
    return client.post(
        f"/webhooks/in/{slug}/",
        data=body,
        content_type="application/json",
        headers=headers,
    )


def test_valid_signature_accepts_and_dispatches(receiver):
    @registry.webhook_handler("stripe")
    def handle(receipt):
        HANDLED.append(receipt.json())

    body = json.dumps({"type": "charge.succeeded"}).encode()
    sig = services.sign("shh", body)
    resp = _post(Client(), "stripe", body, sig)

    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.verified is True
    assert receipt.status == WebhookReceipt.Status.PROCESSED
    assert HANDLED == [{"type": "charge.succeeded"}]
    receiver.refresh_from_db()
    assert receiver.total_received == 1


def test_invalid_signature_rejected(receiver):
    resp = _post(Client(), "stripe", b'{"x":1}', "sha256=bad")
    assert resp.status_code == 401
    receipt = WebhookReceipt.objects.get()
    assert receipt.status == WebhookReceipt.Status.REJECTED
    assert receipt.verified is False


def test_unknown_receiver_404():
    resp = _post(Client(), "nope", b"{}", None)
    assert resp.status_code == 404
    assert WebhookReceipt.objects.count() == 0


def test_disabled_receiver_404(receiver):
    receiver.enabled = False
    receiver.save()
    body = b"{}"
    resp = _post(Client(), "stripe", body, services.sign("shh", body))
    assert resp.status_code == 404


def test_missing_handler_marks_failed(receiver):
    # No handler registered for "stripe".
    body = b"{}"
    resp = _post(Client(), "stripe", body, services.sign("shh", body))
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.status == WebhookReceipt.Status.FAILED
    assert "no handler" in receipt.error


def test_require_signature_off_accepts_unsigned(receiver):
    receiver.require_signature = False
    receiver.save()

    @registry.webhook_handler("stripe")
    def handle(receipt):
        HANDLED.append("ran")

    resp = _post(Client(), "stripe", b"{}", None)
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get()
    assert receipt.verified is False
    assert receipt.status == WebhookReceipt.Status.PROCESSED


# --- public-route hardening (audit 2026-09-13, C6) ---------------------------


def test_rejected_receipt_keeps_an_excerpt_and_digest_not_the_body(receiver):
    body = b'{"pad":"' + b"x" * 50_000 + b'"}'
    assert _post(Client(), "stripe", body, "sha256=bad").status_code == 401
    receipt = WebhookReceipt.objects.get()
    assert len(receipt.body) <= 1024
    assert "sha256" in receipt.error


def test_rejections_stop_being_recorded_after_the_per_minute_cap(receiver, settings):
    settings.SMALLSTACK_WEBHOOK_REJECTED_PER_MINUTE = 3
    for _ in range(6):
        assert _post(Client(), "stripe", b"{}", "sha256=bad").status_code == 401
    assert WebhookReceipt.objects.count() == 3


def test_oversized_body_is_refused_before_anything_is_stored(receiver, settings):
    settings.SMALLSTACK_WEBHOOK_INBOUND_MAX_BYTES = 100
    body = b"{" + b" " * 200 + b"}"
    assert _post(Client(), "stripe", body, services.sign("shh", body)).status_code == 413
    assert WebhookReceipt.objects.count() == 0


def test_prune_webhook_receipts_drops_old_rows(receiver):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    old = WebhookReceipt.objects.create(receiver=receiver, body="old")
    WebhookReceipt.objects.filter(pk=old.pk).update(received_at=timezone.now() - timedelta(days=40))
    new = WebhookReceipt.objects.create(receiver=receiver, body="new")
    call_command("prune_webhook_receipts", "--keep-days", "30", stdout=__import__("io").StringIO())
    assert list(WebhookReceipt.objects.values_list("pk", flat=True)) == [new.pk]
