"""Custom MCP tools for webhooks — the verbs CRUD can't express.

The four CRUDViews already emit list/get/create/update/delete tools for endpoints
and receivers. These add the imperative + aggregate verbs an agent needs:
trigger a test delivery, replay a past one, and summarize delivery health.

Per build-mcp-solution.md: MCP is request/response — these trigger/inspect
webhooks, they never hold a callback.
"""

from __future__ import annotations

from typing import Any

from apps.mcp.server import tool


def summary_deliveries(args: dict[str, Any]) -> dict[str, Any]:
    return _summary()


def _summary() -> dict[str, Any]:
    from django.db.models import Count

    from .models import WebhookDelivery, WebhookEndpoint

    by_status = dict(
        WebhookDelivery.objects.values_list("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )
    return {
        "endpoints_active": WebhookEndpoint.objects.filter(enabled=True).count(),
        "endpoints_total": WebhookEndpoint.objects.count(),
        "deliveries": by_status,
    }


def test_webhook(args: dict[str, Any]) -> dict[str, Any]:
    return _test_webhook(args["endpoint_id"])


def _test_webhook(endpoint_id: int) -> dict[str, Any]:
    from django.utils import timezone

    from . import services
    from .models import WebhookDelivery, WebhookEndpoint

    endpoint = WebhookEndpoint.objects.filter(pk=endpoint_id).first()
    if endpoint is None:
        return {"error": f"endpoint {endpoint_id} not found"}
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint,
        event_type="webhooks.test.ping",
        payload={
            "event": "webhooks.test.ping",
            "action": "test",
            "occurred_at": timezone.now().isoformat(),
            "data": {"message": "Test delivery from SmallStack MCP."},
        },
        max_attempts=1,  # tests don't retry: a failure goes straight to dead
    )
    services._enqueue_delivery(delivery.pk)
    result = {"queued": True, "delivery_id": delivery.pk, "endpoint": endpoint.name}
    if not endpoint.enabled:
        result["note"] = (
            f'endpoint "{endpoint.name}" is disabled — test/replay sends go out, '
            "but signal events will not deliver until it is re-enabled "
            "(update_webhook with enabled=true)"
        )
    return result


def replay_delivery(args: dict[str, Any]) -> dict[str, Any]:
    return _replay(args["delivery_id"])


def _replay(delivery_id: int) -> dict[str, Any]:
    from . import services
    from .models import WebhookDelivery

    original = WebhookDelivery.objects.filter(pk=delivery_id).select_related("endpoint").first()
    if original is None:
        return {"error": f"delivery {delivery_id} not found"}
    replay = services.replay_delivery(original)
    result: dict[str, Any] = {"queued": True, "delivery_id": replay.pk, "replayed_from": delivery_id}
    if not original.endpoint.enabled:
        result["note"] = (
            f'endpoint "{original.endpoint.name}" is disabled — the replay goes out, '
            "but signal events will not deliver until it is re-enabled "
            "(update_webhook with enabled=true)"
        )
    return result


def replay_dead_deliveries(args: dict[str, Any]) -> dict[str, Any]:
    return _replay_dead(args.get("endpoint_id"), args.get("limit", 100))


def _replay_dead(endpoint_id: int | None, limit: int) -> dict[str, Any]:
    """Bulk-replay dead deliveries, reusing each event_id."""
    from . import services

    new_ids = services.replay_dead(endpoint_id=endpoint_id, limit=int(limit))
    return {"queued": len(new_ids), "delivery_ids": new_ids}


def register_webhook_tools() -> None:
    """Register the custom webhook MCP tools.

    Idempotent — ``apps.mcp.server.tool`` dedups by name — so it's safe to
    call at import time (for startup) and again from the test suite after
    ``clear_registry_for_tests()`` wipes the shared MCP registry. Mirrors
    ``register_runbook_tools`` / ``register_search_tools``.
    """
    tool(
        "summary_deliveries",
        "Counts of outbound webhook deliveries by status (pending/retrying/success/"
        "failed/dead). Use this instead of list_* when only the health totals matter.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        requires_access="staff",
    )(summary_deliveries)
    tool(
        "test_webhook",
        "Send a sample signed test delivery to a webhook endpoint by id, so you can "
        "confirm it is reachable. Returns the created delivery id.",
        input_schema={
            "type": "object",
            "properties": {"endpoint_id": {"type": "integer"}},
            "required": ["endpoint_id"],
            "additionalProperties": False,
        },
        write=True,
        requires_access="staff",
    )(test_webhook)
    tool(
        "replay_delivery",
        "Re-send a past webhook delivery by id as a fresh attempt (useful for a "
        "delivery that died). Reuses the original event_id so consumers dedupe. "
        "Returns the new delivery id.",
        input_schema={
            "type": "object",
            "properties": {"delivery_id": {"type": "integer"}},
            "required": ["delivery_id"],
            "additionalProperties": False,
        },
        write=True,
        requires_access="staff",
    )(replay_delivery)
    tool(
        "replay_dead_deliveries",
        "Bulk-replay every DEAD webhook delivery (optionally scoped to one endpoint) as "
        "fresh attempts, reusing each event_id. The dead-letter recovery verb after an "
        "outage. Returns the count and new delivery ids.",
        input_schema={
            "type": "object",
            "properties": {
                "endpoint_id": {"type": "integer"},
                "limit": {"type": "integer", "default": 100},
            },
            "additionalProperties": False,
        },
        write=True,
        requires_access="staff",
    )(replay_dead_deliveries)


register_webhook_tools()
