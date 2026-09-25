"""Reference adapter acceptance: Azure Event Grid built purely on the four seams
(F-028). Proves the validation handshake + a signed event flow both directions with
ZERO core edits — the adapter uses only the public hook API.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.webhooks import hooks, registry
from apps.webhooks.contrib import eventgrid
from apps.webhooks.models import (
    WebhookDelivery,
    WebhookEndpoint,
    WebhookReceipt,
    WebhookReceiver,
)
from apps.webhooks.tasks import deliver_webhook

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def register_adapter():
    hooks.clear_hooks_for_tests()
    registry.clear_handlers_for_tests()
    eventgrid.register()
    yield
    hooks.clear_hooks_for_tests()
    registry.clear_handlers_for_tests()


def _post(slug, body: bytes, headers=None):
    return Client().post(
        f"/webhooks/in/{slug}/", data=body, content_type="application/json", headers=headers or {}
    )


# --- Inbound: challenge handshake --------------------------------------------


def test_eventgrid_validation_handshake_echoes_code():
    WebhookReceiver.objects.create(
        name="EG in", slug="eg", secret="topickey", verifier="eventgrid",
        challenge="eventgrid", require_signature=True,
    )
    body = json.dumps([{
        "id": "1", "eventType": eventgrid.VALIDATION_EVENT,
        "data": {"validationCode": "512d38b6-c7b8-40c8-89fe-f46f9e9622b6"},
    }]).encode()
    # The validation event arrives WITHOUT the key header (Azure sends it unsigned);
    # the challenge seam short-circuits before verification, so it still succeeds.
    resp = _post("eg", body)
    assert resp.status_code == 200
    assert resp.json()["validationResponse"] == "512d38b6-c7b8-40c8-89fe-f46f9e9622b6"
    assert WebhookReceipt.objects.count() == 0  # handshake short-circuits before a receipt


# --- Inbound: signed event verify --------------------------------------------


def test_eventgrid_signed_event_verifies_and_dispatches():
    rec = WebhookReceiver.objects.create(
        name="EG in", slug="eg", secret="topickey", verifier="eventgrid",
        challenge="eventgrid", require_signature=True,
    )
    handled = []

    @registry.webhook_handler("eg")
    def handle(receipt):
        handled.append(receipt.json())

    body = json.dumps([{"id": "e1", "eventType": "Custom.Thing", "data": {"x": 1}}]).encode()
    resp = _post("eg", body, {"aeg-sas-key": "topickey"})
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get(receiver=rec)
    assert receipt.verified is True
    assert receipt.status == WebhookReceipt.Status.PROCESSED
    assert handled and handled[0][0]["eventType"] == "Custom.Thing"


def test_eventgrid_wrong_key_rejected():
    WebhookReceiver.objects.create(
        name="EG in", slug="eg", secret="topickey", verifier="eventgrid", require_signature=True
    )
    body = json.dumps([{"id": "e1", "eventType": "Custom.Thing", "data": {}}]).encode()
    resp = _post("eg", body, {"aeg-sas-key": "WRONG"})
    assert resp.status_code == 401


# --- Outbound: transform + auth ----------------------------------------------


def test_eventgrid_outbound_transform_and_sas(monkeypatch):
    ep = WebhookEndpoint.objects.create(
        name="EG out", target_url="https://topic.eventgrid.azure.net/api/events",
        secret="OUTKEY", transform="eventgrid", auth_scheme="eventgrid-sas",
    )
    d = WebhookDelivery.objects.create(
        endpoint=ep,
        event_type="inventory.item.created",
        payload={
            "event": "inventory.item.created",
            "event_id": "abc-123",
            "occurred_at": "2026-07-26T00:00:00Z",
            "model": "inventory.item",
            "resource": {"type": "inventory.item", "id": 7, "url": "https://a/x/7/"},
            "data": {"id": 7, "name": "Widget"},
        },
    )
    sink = {}

    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        sink["headers"] = dict(req.headers)
        sink["body"] = req.data
        return FakeResp()

    monkeypatch.setattr("apps.webhooks.tasks._open", fake)
    deliver_webhook.func(d.pk)

    # Event Grid schema: an array of events, mapped off the SmallStack envelope.
    sent = json.loads(sink["body"])
    assert isinstance(sent, list) and len(sent) == 1
    eg = sent[0]
    assert eg["eventType"] == "inventory.item.created"
    assert eg["id"] == "abc-123"
    assert eg["subject"] == "https://a/x/7/"
    assert eg["data"] == {"id": 7, "name": "Widget"}
    # SAS key auth header present; default HMAC signature absent.
    assert sink["headers"]["Aeg-sas-key"] == "OUTKEY"
    assert "X-smallstack-signature" not in sink["headers"]
