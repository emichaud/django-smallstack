"""The custom webhook MCP tools (test_webhook / replay_delivery / summary_deliveries).

We drive the inner functions directly (the tool entry points are trivial
pass-throughs that unpack args), plus one entry-point smoke test.
"""

from __future__ import annotations

from unittest import mock

import pytest

from apps.webhooks import mcp_tools
from apps.webhooks.models import WebhookDelivery, WebhookEndpoint

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_real_enqueue():
    with mock.patch("apps.webhooks.services._enqueue_delivery") as m:
        yield m


def test_registered_in_tool_registry():
    from apps.mcp.server import TOOL_REGISTRY

    for name in ("test_webhook", "replay_delivery", "summary_deliveries"):
        assert name in TOOL_REGISTRY
    # the imperative tools must be write + staff-gated
    assert TOOL_REGISTRY["test_webhook"].write is True
    assert TOOL_REGISTRY["test_webhook"].requires_access == "staff"


def test_summary_counts_by_status():
    ep = WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")
    WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={}, status="success")
    WebhookDelivery.objects.create(endpoint=ep, event_type="t", payload={}, status="dead")
    out = mcp_tools._summary()
    assert out["endpoints_total"] == 1
    assert out["deliveries"]["success"] == 1
    assert out["deliveries"]["dead"] == 1


def test_test_webhook_creates_delivery(no_real_enqueue):
    ep = WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")
    out = mcp_tools._test_webhook(ep.pk)
    assert out["queued"] is True
    d = WebhookDelivery.objects.get(pk=out["delivery_id"])
    assert d.event_type == "webhooks.test.ping"
    no_real_enqueue.assert_called_once_with(d.pk)


def test_test_webhook_unknown_endpoint():
    assert "error" in mcp_tools._test_webhook(999999)


def test_replay_clones(no_real_enqueue):
    ep = WebhookEndpoint.objects.create(name="e", target_url="https://hooks.example.com/x")
    orig = WebhookDelivery.objects.create(endpoint=ep, event_type="a.b.c", payload={"x": 1}, status="dead")
    out = mcp_tools._replay(orig.pk)
    replay = WebhookDelivery.objects.get(pk=out["delivery_id"])
    assert replay.pk != orig.pk
    assert replay.payload == {"x": 1}


def test_tool_entry_point_runs(no_real_enqueue):
    """The registered tool entry point returns the summary directly."""
    out = mcp_tools.summary_deliveries({})
    assert "deliveries" in out
