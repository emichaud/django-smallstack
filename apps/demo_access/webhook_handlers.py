"""Scenario C inbound webhook handler — the local receiver, loop-safe.

The seed creates a ``WebhookReceiver`` with slug ``access-grants`` plus an
outbound ``WebhookEndpoint`` that posts
``smallstack_approvals.approvalrequest.*`` back to it. This handler records what
arrived into ``WebhookEcho`` so the tester can read the fan-out without parsing
raw receipts.

Handlers run inside ``suppress_webhooks()`` (docs/skills/webhooks.md "loop
guard"), so the WebhookEcho write emits no further events even though the
delivery path is a real round-trip.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.webhooks.registry import webhook_handler

from .models import WebhookEcho

logger = logging.getLogger("smallstack.demo_access")

RECEIVER_SLUG = "access-grants"


@webhook_handler(RECEIVER_SLUG)
def on_approval_event(receipt: Any) -> None:
    """Record one approvals webhook delivery."""
    event = receipt.json() or {}
    data = event.get("data") or {}
    resource = event.get("resource") or {}
    WebhookEcho.objects.create(
        event_type=str(event.get("event") or event.get("event_type") or "")[:200],
        approval_id=data.get("id") or resource.get("id"),
        status=str(data.get("status") or "")[:20],
        title=str(data.get("title") or "")[:200],
        payload=event,
    )
