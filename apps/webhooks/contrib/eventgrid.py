"""Reference adapter: **Azure Event Grid**, built purely on the four webhook seams.

This module is the *proof* that the seams are enough: a complete two-way Event Grid
integration with **zero core edits**, using only the public ``apps.webhooks`` hook API.
It is a *reference* (not auto-registered in the base template) — a downstream project
copies it into its own ``webhook_transforms.py`` / ``webhook_auths.py`` /
``webhook_verifiers.py`` / ``webhook_challenges.py`` (or imports :func:`register` from an
app's ``ready()``) and selects the schemes per endpoint / receiver:

    endpoint.transform   = "eventgrid"       # outbound → Event Grid / CloudEvents schema
    endpoint.auth_scheme = "eventgrid-sas"   # outbound → aeg-sas-key header
    receiver.verifier    = "eventgrid"       # inbound  → aeg-sas-token / key check
    receiver.challenge   = "eventgrid"       # inbound  → SubscriptionValidation echo

All four seams are exercised. See docs/skills/webhooks.md → "Reference adapter".
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from apps.webhooks import (
    AuthResult,
    OutgoingRequest,
    Transformed,
    webhook_auth,
    webhook_challenge,
    webhook_transform,
    webhook_verifier,
)

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

    from apps.webhooks.models import WebhookEndpoint, WebhookReceiver

# The header Event Grid uses for its shared-access-key auth.
SAS_HEADER = "aeg-sas-key"
# The Event Grid validation event type (handshake).
VALIDATION_EVENT = "Microsoft.EventGrid.SubscriptionValidationEvent"


# ---------------------------------------------------------------------------
# Outbound — @webhook_transform + @webhook_auth
# ---------------------------------------------------------------------------


def to_eventgrid(event: dict[str, Any]) -> Transformed:
    """Reshape the SmallStack envelope into the Event Grid event schema.

    Event Grid expects an array of events, each with eventType / subject / eventTime /
    id / data. We map straight off the (upgraded) SmallStack envelope keys.
    """
    eg_event = {
        "id": event.get("event_id") or "",
        "eventType": event.get("event", ""),
        "subject": (event.get("resource") or {}).get("url") or event.get("model", ""),
        "eventTime": event.get("occurred_at", ""),
        "dataVersion": "1.0",
        "data": event.get("data", {}),
    }
    return Transformed(
        body=json.dumps([eg_event], default=str).encode(),
        content_type="application/json",
    )


def sign_sas(req: OutgoingRequest, endpoint: WebhookEndpoint) -> AuthResult:
    """Event Grid custom-topic auth: the endpoint key in the ``aeg-sas-key`` header."""
    return AuthResult(headers={SAS_HEADER: endpoint.secret})


# ---------------------------------------------------------------------------
# Inbound — @webhook_challenge + @webhook_verifier
# ---------------------------------------------------------------------------


def eg_validate(request: HttpRequest, receiver: WebhookReceiver) -> HttpResponse | None:
    """Answer the Event Grid subscription-validation handshake.

    On a ``SubscriptionValidationEvent`` echo the ``validationCode`` in a
    ``{"validationResponse": <code>}`` body (200) to complete the handshake. Any other
    payload returns None to fall through to normal verify + dispatch.
    """
    from django.http import JsonResponse

    try:
        payload = json.loads(request.body or b"[]")
    except (ValueError, TypeError):
        return None
    events = payload if isinstance(payload, list) else [payload]
    for ev in events:
        if isinstance(ev, dict) and ev.get("eventType") == VALIDATION_EVENT:
            code = (ev.get("data") or {}).get("validationCode")
            if code:
                return JsonResponse({"validationResponse": code})
    return None


def verify_eventgrid(body: bytes, headers: Mapping[str, str], receiver: WebhookReceiver) -> bool:
    """Verify Event Grid's ``aeg-sas-key`` against the receiver secret (constant-time).

    ``headers`` is case-insensitive (see hooks.Verifier), so either spelling hits.
    """
    provided = headers.get("Aeg-Sas-Key") or headers.get(SAS_HEADER) or ""
    if not provided:
        return False
    return hmac.compare_digest(provided, receiver.secret)


# ---------------------------------------------------------------------------
# Registration — call from an app's ready() (or copy the decorators into
# webhook_*.py to be autodiscovered).
# ---------------------------------------------------------------------------


def register() -> None:
    """Register all four Event Grid seams. Idempotent (first-wins)."""
    webhook_transform("eventgrid")(to_eventgrid)
    webhook_auth("eventgrid-sas")(sign_sas)
    webhook_verifier("eventgrid")(verify_eventgrid)
    webhook_challenge("eventgrid")(eg_validate)
