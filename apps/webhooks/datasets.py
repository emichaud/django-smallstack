"""Bundled datasets for webhooks: endpoints, deliveries, receivers, receipts.

Secrets, custom headers, payloads and raw bodies are deliberately not columns.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.datasets.framework import framework_dataset

from .models import WebhookDelivery, WebhookEndpoint, WebhookReceipt, WebhookReceiver


@framework_dataset(
    "smallstack_webhook_endpoints",
    label="Webhook endpoints",
    description=(
        "Outbound webhook targets: where they post, whether they are enabled or paired, and their "
        "delivery health counters."
    ),
    columns=[
        "name",
        "target_url",
        "enabled",
        "is_paired",
        "transform",
        "auth_scheme",
        "owner",
        "last_delivery_at",
        "last_status",
        "total_deliveries",
        "consecutive_failures",
        "created_at",
        "updated_at",
    ],
    filterable=[
        "enabled",
        "is_paired",
        "transform",
        "auth_scheme",
        "owner",
        "last_status",
        "last_delivery_at",
        "created_at",
    ],
)
def webhook_endpoints() -> QuerySet[WebhookEndpoint]:
    return WebhookEndpoint.objects.select_related("owner")


@framework_dataset(
    "smallstack_webhook_deliveries",
    label="Webhook deliveries",
    description=(
        "One row per outbound delivery attempt chain: endpoint, event, status, attempt count, the remote "
        "response code and latency."
    ),
    columns=[
        "created_at",
        "endpoint",
        "event_type",
        "event_id",
        "status",
        "attempt",
        "max_attempts",
        "next_attempt_at",
        "response_status",
        "response_ms",
        "error",
        "updated_at",
    ],
    filterable=["created_at", "endpoint", "event_type", "status", "response_status", "next_attempt_at", "updated_at"],
)
def webhook_deliveries() -> QuerySet[WebhookDelivery]:
    return WebhookDelivery.objects.select_related("endpoint")


@framework_dataset(
    "smallstack_webhook_receivers",
    label="Webhook receivers",
    description=(
        "Inbound webhook receivers: handler, verification posture, whether enabled or paired, and receipt counters."
    ),
    columns=[
        "name",
        "slug",
        "handler",
        "require_signature",
        "verifier",
        "challenge",
        "enabled",
        "is_paired",
        "owner",
        "last_received_at",
        "total_received",
        "created_at",
        "updated_at",
    ],
    filterable=[
        "handler",
        "require_signature",
        "verifier",
        "enabled",
        "is_paired",
        "owner",
        "last_received_at",
        "created_at",
    ],
)
def webhook_receivers() -> QuerySet[WebhookReceiver]:
    return WebhookReceiver.objects.select_related("owner")


@framework_dataset(
    "smallstack_webhook_receipts",
    label="Webhook receipts",
    description=(
        "One row per inbound webhook received: receiver, source address, whether the signature verified, "
        "origin, and processing outcome."
    ),
    columns=["received_at", "receiver", "source_ip", "verified", "origin", "status", "error", "task_result_id"],
    filterable=["received_at", "receiver", "source_ip", "verified", "origin", "status"],
)
def webhook_receipts() -> QuerySet[WebhookReceipt]:
    return WebhookReceipt.objects.select_related("receiver")
