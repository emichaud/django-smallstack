"""webhook_doctor — the PASS / WARN / FAIL health checks."""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.webhooks.models import WebhookDelivery, WebhookEndpoint, WebhookReceiver
from apps.webhooks.views import WebhookReceiverCRUDView

pytestmark = pytest.mark.django_db


def _report(*args) -> list[dict]:
    out = StringIO()
    call_command("webhook_doctor", "--json", *args, stdout=out)
    return json.loads(out.getvalue())


def _status(report, name_contains):
    for row in report:
        if name_contains.lower() in row["name"].lower():
            return row["status"]
    return None


def test_no_optin_warns_outbound_registry(monkeypatch):
    # The framework itself ships opted-in models (approvals since v0.21) — build
    # the zero-opt-in baseline explicitly to prove the doctor warns on it.
    from apps.smallstack.crud import CRUDView

    for view in set(CRUDView._registry.values()):
        if getattr(view, "enable_webhooks", False):
            monkeypatch.setattr(view, "enable_webhooks", False)
    report = _report()
    assert _status(report, "Outbound registry") == "WARN"


def test_optin_model_passes_registry():
    original = WebhookReceiverCRUDView.enable_webhooks
    WebhookReceiverCRUDView.enable_webhooks = True
    try:
        report = _report()
        assert _status(report, "Outbound registry") == "PASS"
    finally:
        WebhookReceiverCRUDView.enable_webhooks = original


def test_bad_endpoint_url_fails(settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = False
    WebhookEndpoint.objects.create(
        name="loopback", target_url="http://127.0.0.1:9000/x", event_filter=["*"]
    )
    report = _report()
    assert _status(report, "Endpoint URLs") == "FAIL"


def test_empty_filter_warns():
    WebhookEndpoint.objects.create(
        name="inert", target_url="https://hooks.example.com/x", event_filter=[]
    )
    report = _report()
    assert _status(report, "Endpoint filters") == "WARN"


def test_stuck_retry_fails_delivery_tick(settings):
    settings.SMALLSTACK_SCHEDULER_OVERDUE_GRACE_SECONDS = 60
    ep = WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")
    WebhookDelivery.objects.create(
        endpoint=ep,
        event_type="t",
        payload={},
        status=WebhookDelivery.Status.RETRYING,
        next_attempt_at=timezone.now() - timedelta(hours=1),
    )
    report = _report()
    assert _status(report, "Delivery tick") == "FAIL"


def test_receiver_without_handler_fails():
    WebhookReceiver.objects.create(name="Stripe", slug="stripe")  # no handler registered
    report = _report()
    assert _status(report, "Inbound handlers") == "FAIL"


def test_check_only_exits_nonzero_on_fail(settings):
    settings.SMALLSTACK_WEBHOOK_ALLOW_PRIVATE = False
    WebhookEndpoint.objects.create(
        name="loopback", target_url="http://127.0.0.1:9000/x", event_filter=["*"]
    )
    with pytest.raises(SystemExit):
        call_command("webhook_doctor", "--check-only", stdout=StringIO())


def test_explain_lists_handlers_and_models():
    out = StringIO()
    call_command("webhook_doctor", "--explain", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert "outbound_models" in data
    assert "inbound_handlers" in data


def test_unsigned_receiver_warns():
    """[F-003] An enabled receiver with require_signature=False fails open —
    the doctor must call it out."""
    from apps.webhooks.registry import webhook_handler

    @webhook_handler("unsigned-doctor")
    def _handler(receipt):  # pragma: no cover — never dispatched here
        pass

    WebhookReceiver.objects.create(
        name="Unsigned", slug="unsigned-doctor", require_signature=False
    )
    report = _report()
    assert _status(report, "Inbound signatures") == "WARN"


def test_signed_receivers_no_signature_warning():
    from apps.webhooks.registry import webhook_handler

    @webhook_handler("signed-doctor")
    def _handler(receipt):  # pragma: no cover
        pass

    WebhookReceiver.objects.create(name="Signed", slug="signed-doctor")
    report = _report()
    assert _status(report, "Inbound signatures") is None


def test_unresolved_origin_warns(settings):
    """[F-029] With neither SMALLSTACK_WEBHOOK_ORIGIN nor a URL-shaped SITE_URL set, the
    origin falls back to a bare hostname and resource.url degrades to null — WARN."""
    settings.SMALLSTACK_WEBHOOK_ORIGIN = ""
    settings.SITE_URL = ""
    report = _report()
    row = next(r for r in report if "webhook origin" in r["name"].lower())
    assert row["status"] == "WARN"
    assert "SITE_URL" in row["detail"] and "SMALLSTACK_WEBHOOK_ORIGIN" in row["detail"]


def test_configured_origin_passes(settings):
    settings.SMALLSTACK_WEBHOOK_ORIGIN = "https://mysite.example.com"
    report = _report()
    assert _status(report, "Webhook origin") == "PASS"
