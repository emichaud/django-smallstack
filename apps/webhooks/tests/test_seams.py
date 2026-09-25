"""The four extension seams register and take effect (F-019, F-025, F-016, F-026).

Each seam has a built-in default that reproduces today's behavior; a custom plug-in is
selected per endpoint / per receiver by name. These tests register a trivial custom hook
and prove it's what runs on the wire (outbound) or at the door (inbound).
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.webhooks import (
    AuthResult,
    Transformed,
    hooks,
    registry,
    webhook_auth,
    webhook_challenge,
    webhook_transform,
    webhook_verifier,
)
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint, WebhookReceipt, WebhookReceiver
from apps.webhooks.tasks import deliver_webhook

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_hooks():
    hooks.clear_hooks_for_tests()
    registry.clear_handlers_for_tests()
    yield
    hooks.clear_hooks_for_tests()
    registry.clear_handlers_for_tests()


def _capture_urlopen(monkeypatch, sink):
    class FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        sink["url"] = req.full_url
        sink["headers"] = dict(req.headers)
        sink["body"] = req.data
        return FakeResp()

    monkeypatch.setattr("apps.webhooks.tasks._open", fake)


# --- F-019 outbound transform ------------------------------------------------


def test_default_transform_is_current_envelope(monkeypatch):
    ep = WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")
    d = WebhookDelivery.objects.create(
        endpoint=ep, event_type="t.t.created", payload={"event": "t.t.created", "data": {"id": 1}}
    )
    sink = {}
    _capture_urlopen(monkeypatch, sink)
    deliver_webhook.func(d.pk)
    assert json.loads(sink["body"]) == {"event": "t.t.created", "data": {"id": 1}}
    assert sink["headers"]["Content-type"] == "application/json"


def test_custom_transform_reshapes_body(monkeypatch):
    @webhook_transform("slack")
    def to_slack(event):
        return Transformed(
            body=json.dumps({"text": f"{event['event']} fired"}).encode(),
            content_type="application/json",
        )

    ep = WebhookEndpoint.objects.create(
        name="e", target_url="https://hooks.example.com/x", transform="slack"
    )
    d = WebhookDelivery.objects.create(
        endpoint=ep, event_type="inv.item.low", payload={"event": "inv.item.low", "data": {}}
    )
    sink = {}
    _capture_urlopen(monkeypatch, sink)
    deliver_webhook.func(d.pk)
    assert json.loads(sink["body"]) == {"text": "inv.item.low fired"}


def test_unknown_transform_falls_back_to_default(monkeypatch):
    ep = WebhookEndpoint.objects.create(
        name="e", target_url="https://hooks.example.com/x", transform="does-not-exist"
    )
    d = WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={"data": 1})
    sink = {}
    _capture_urlopen(monkeypatch, sink)
    deliver_webhook.func(d.pk)  # must not crash — falls back to smallstack envelope
    assert json.loads(sink["body"]) == {"data": 1}


# --- F-025 outbound auth -----------------------------------------------------


def test_default_auth_adds_hmac_signature(monkeypatch):
    ep = WebhookEndpoint.objects.create(
        name="e", target_url="https://hooks.example.com/x", secret="s3cr3t"
    )
    d = WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={"a": 1})
    sink = {}
    _capture_urlopen(monkeypatch, sink)
    deliver_webhook.func(d.pk)
    assert sink["headers"]["X-smallstack-signature"].startswith("sha256=")


def test_custom_auth_adds_header_and_query(monkeypatch):
    @webhook_auth("sas")
    def sign_sas(req, endpoint):
        return AuthResult(headers={"aeg-sas-key": endpoint.secret}, params={"api-version": "2018"})

    ep = WebhookEndpoint.objects.create(
        name="e", target_url="https://eg.example.com/x", secret="KEY123", auth_scheme="sas"
    )
    d = WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={})
    sink = {}
    _capture_urlopen(monkeypatch, sink)
    deliver_webhook.func(d.pk)
    assert sink["headers"]["Aeg-sas-key"] == "KEY123"
    assert "api-version=2018" in sink["url"]
    # No default HMAC header when a custom scheme is selected.
    assert "X-smallstack-signature" not in sink["headers"]


# --- F-016 inbound verifier --------------------------------------------------


def _post(slug, body: bytes, headers):
    return Client().post(
        f"/webhooks/in/{slug}/", data=body, content_type="application/json", headers=headers
    )


def test_custom_verifier_accepts_stripe_scheme():
    """A Stripe-style t.body verifier — the escape hatch that supersedes
    require_signature=False fail-open (F-016/F-017)."""
    import hashlib
    import hmac

    @webhook_verifier("stripe")
    def verify_stripe(body, headers, receiver):
        header = headers.get("Stripe-Signature", "")
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        t, v1 = parts.get("t", ""), parts.get("v1", "")
        expected = hmac.new(receiver.secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)

    rec = WebhookReceiver.objects.create(
        name="Stripe", slug="stripe", secret="whsec_x", verifier="stripe"
    )

    @registry.webhook_handler("stripe")
    def handle(receipt):
        pass

    ts, body = "1750000000", b'{"id":"evt_1"}'
    v1 = hmac.new(b"whsec_x", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    resp = _post("stripe", body, {"Stripe-Signature": f"t={ts},v1={v1}"})
    assert resp.status_code == 202
    receipt = WebhookReceipt.objects.get(receiver=rec)
    assert receipt.verified is True
    assert receipt.status == WebhookReceipt.Status.PROCESSED


def test_custom_verifier_rejects_bad_signature():
    @webhook_verifier("always-false")
    def nope(body, headers, receiver):
        return False

    WebhookReceiver.objects.create(name="R", slug="r", secret="x", verifier="always-false")
    resp = _post("r", b"{}", {})
    assert resp.status_code == 401


# --- F-026 inbound challenge -------------------------------------------------


def test_challenge_short_circuits_before_dispatch():
    from django.http import JsonResponse

    @webhook_challenge("eventgrid")
    def eg_validate(request, receiver):
        payload = json.loads(request.body or b"[]")
        if isinstance(payload, list) and payload and payload[0].get("eventType") == "Validation":
            code = payload[0]["data"]["validationCode"]
            return JsonResponse({"validationResponse": code})
        return None  # fall through to normal dispatch

    WebhookReceiver.objects.create(
        name="EG", slug="eg", secret="x", challenge="eventgrid", require_signature=False
    )

    handled = []

    @registry.webhook_handler("eg")
    def handle(receipt):
        handled.append(True)

    # Validation handshake short-circuits and echoes the code.
    body = json.dumps([{"eventType": "Validation", "data": {"validationCode": "abc-123"}}]).encode()
    resp = _post("eg", body, {})
    assert resp.status_code == 200
    assert resp.json()["validationResponse"] == "abc-123"
    assert handled == []  # dispatch did NOT run
    assert WebhookReceipt.objects.count() == 0  # short-circuited before receipt

    # A real event falls through to dispatch.
    resp = _post("eg", json.dumps([{"eventType": "Real"}]).encode(), {})
    assert resp.status_code == 202
    assert handled == [True]


def test_no_challenge_by_default():
    """A receiver with challenge='' runs no handshake (fall straight through)."""
    WebhookReceiver.objects.create(name="R", slug="r", secret="x", require_signature=False)

    @registry.webhook_handler("r")
    def handle(receipt):
        pass

    resp = _post("r", b"{}", {})
    assert resp.status_code == 202
