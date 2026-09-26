"""Webhook models — outbound (Endpoint + Delivery) and inbound (Receiver + Receipt).

The design mirrors the scheduler's proven split: a **config** model an operator
manages, plus an **append-only attempt/receipt** model that records what actually
happened. Execution (the HTTP round-trip) is owned by a ``django.tasks`` task; the
Delivery/Receipt row owns state, retry cadence, and history.

Outbound:  WebhookEndpoint  → WebhookDelivery (one per fan-out, retried on failure)
Inbound:   WebhookReceiver  → WebhookReceipt  (one per received POST)
"""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

# Length of the raw signing/verifying secret (token_urlsafe chars, ~1.3×bytes).
SECRET_BYTES = 32
# Chars of the secret shown in the UI as a non-revealing hint.
SECRET_PREVIEW_LEN = 6


def generate_secret() -> str:
    """A fresh signing/verifying secret. Reuses the APIToken generator idiom
    (``secrets.token_urlsafe``) but the value is stored **recoverably** — an HMAC
    secret must be read back to sign every payload, so it cannot be one-way
    hashed the way APIToken.hashed_key is."""
    return secrets.token_urlsafe(SECRET_BYTES)


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------


class WebhookEndpoint(models.Model):
    """A registered external URL that receives signed POSTs when data changes.

    An endpoint subscribes to a set of event types via ``event_filter`` (fnmatch
    patterns over ``<app_label>.<model>.<action>``, e.g. ``scheduler.scheduledjob.*``
    or ``*.created`` or ``*``). Every enabled endpoint whose filter matches a fired
    event gets exactly one WebhookDelivery.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RETRYING = "retrying", "Retrying"
        DEAD = "dead", "Dead"

    name = models.CharField(max_length=200)
    target_url = models.URLField(
        max_length=500,
        help_text="Where signed event POSTs are sent.",
    )
    # Stored recoverably (not hashed) — needed to compute the HMAC on every send.
    secret = models.CharField(
        max_length=100,
        default=generate_secret,
        help_text="Signing key. The receiver verifies X-SmallStack-Signature with it.",
    )
    # fnmatch patterns over "<app_label>.<model>.<action>". Empty ⇒ matches nothing
    # (an endpoint with no filter is inert rather than a firehose by accident).
    event_filter = models.JSONField(
        default=list,
        blank=True,
        help_text='Event patterns, e.g. ["scheduler.scheduledjob.*", "*.created"].',
    )
    # Optional static headers merged into every request (e.g. an auth header the
    # receiver expects). Never override the signature/event headers we set.
    headers = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)

    # True iff created by `sc webhook pair` (F-031). The pairing flow only ever
    # adopts/updates objects it owns, so a hand-made endpoint to the same URL is never
    # touched by a re-pair.
    is_paired = models.BooleanField(
        default=False,
        help_text="Managed by the SmallStack↔SmallStack pairing flow (read-only).",
    )

    # Extension seams (see apps/webhooks/hooks.py). Both default to today's behavior:
    # transform="smallstack" emits the current envelope; auth_scheme="hmac" adds the
    # current X-SmallStack-Signature. A blank value is normalized to the default.
    transform = models.CharField(
        max_length=64,
        default="smallstack",
        blank=True,
        help_text="Outbound payload transform (@webhook_transform name). Default: smallstack envelope.",
    )
    auth_scheme = models.CharField(
        max_length=64,
        default="hmac",
        blank=True,
        help_text="Outbound auth scheme (@webhook_auth name). Default: hmac (X-SmallStack-Signature).",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhook_endpoints",
        null=True,
        blank=True,
    )

    # Bookkeeping maintained by the delivery task.
    last_delivery_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=10, choices=Status.choices, blank=True)
    total_deliveries = models.PositiveIntegerField(default=0)
    consecutive_failures = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Webhook Endpoint"
        verbose_name_plural = "Webhook Endpoints"

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        """Reject an unroutable / disallowed target at save time, not at send time."""
        from . import services

        if self.target_url:
            ok, reason = services.url_is_allowed(self.target_url)
            if not ok:
                raise ValidationError({"target_url": reason})
        if self.event_filter and not isinstance(self.event_filter, list):
            raise ValidationError({"event_filter": "Must be a list of patterns."})

    @property
    def secret_preview(self) -> str:
        """Non-revealing hint for list/detail views (first few chars + ellipsis)."""
        if not self.secret:
            return "—"
        return f"{self.secret[:SECRET_PREVIEW_LEN]}…"

    def matches(self, event_type: str) -> bool:
        """True if any pattern in event_filter matches this event type."""
        from fnmatch import fnmatch

        return any(fnmatch(event_type, pat) for pat in (self.event_filter or []))


class WebhookDelivery(models.Model):
    """One attempt-tracked delivery of one event to one endpoint (append-only).

    ``status`` is the delivery-side view. ``next_attempt_at`` is the retry cursor
    the tick claims. The HTTP outcome (response code / latency / error) is recorded
    here directly rather than joined from the task engine, because unlike the
    scheduler we own the request and want the response detail inline.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RETRYING = "retrying", "Retrying"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        DEAD = "dead", "Dead"

    endpoint = models.ForeignKey(
        WebhookEndpoint, on_delete=models.CASCADE, related_name="deliveries"
    )
    event_type = models.CharField(max_length=200, db_index=True)
    payload = models.JSONField(default=dict)
    # Stable per-event idempotency key: minted once when the signal fires and REUSED by
    # replay (a new delivery row, same event_id), so a consumer dedupes an operator
    # replay against the original. Sent as X-SmallStack-Event-Id. Nullable for rows
    # created before this field existed; new rows always get one.
    event_id = models.UUIDField(null=True, blank=True, db_index=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    # The retry cursor: set when status=retrying, cleared when claimed/terminal.
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)

    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    # UUID of the django.tasks DBTaskResult that ran the send (best-effort link).
    task_result_id = models.CharField(max_length=64, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Webhook Delivery"
        verbose_name_plural = "Webhook Deliveries"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["endpoint", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} → {self.endpoint_id} ({self.status})"

    @property
    def endpoint_name(self) -> str:
        return self.endpoint.name

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.SUCCESS, self.Status.DEAD}


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


class WebhookReceiver(models.Model):
    """A named inbound endpoint at ``/webhooks/in/<slug>/`` that external systems
    POST to. The request signature is verified against ``secret`` and a matching
    handler (registered via ``@webhook_handler(slug)``) processes the payload in
    the background.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL segment: POSTs arrive at /webhooks/in/<slug>/.",
    )
    # Registered handler name (defaults to the slug). Resolved from the
    # @webhook_handler registry at dispatch time.
    handler = models.CharField(
        max_length=100,
        blank=True,
        help_text="Registered handler name. Blank ⇒ use the slug.",
    )
    secret = models.CharField(max_length=100, default=generate_secret)
    # Defaults to the header SmallStack's own sender emits, so pairing two
    # SmallStack installs works out of the box. It used to default to
    # "X-Signature" while services.SIGNATURE_HEADER is
    # "X-SmallStack-Signature", so a receiver created with defaults 401'd every
    # delivery from a SmallStack endpoint. Any spelling is still accepted for
    # third-party senders, and the lookup is case-insensitive. (F-06.)
    signature_header = models.CharField(
        max_length=80,
        default="X-SmallStack-Signature",
        help_text=(
            "Request header carrying the HMAC-SHA256 hex digest. Matched "
            "case-insensitively. Default matches SmallStack's own sender; set "
            "e.g. 'X-Signature' or 'X-Hub-Signature-256' for a third party."
        ),
    )
    # When off, signature failures are logged but the payload is still accepted —
    # useful while onboarding a sender that doesn't sign yet. Default on.
    require_signature = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)

    # True iff created by `sc webhook pair` (F-031). The pairing flow only ever
    # adopts/updates objects it owns, so a hand-made receiver on the same slug is never
    # touched by a re-pair.
    is_paired = models.BooleanField(
        default=False,
        help_text="Managed by the SmallStack↔SmallStack pairing flow (read-only).",
    )

    # Extension seams (see apps/webhooks/hooks.py). Both default to today's behavior:
    # verifier="hmac" is the current raw-body HMAC check; challenge="" runs no handshake.
    verifier = models.CharField(
        max_length=64,
        default="hmac",
        blank=True,
        help_text="Inbound signature verifier (@webhook_verifier name). Default: hmac (raw-body HMAC).",
    )
    challenge = models.CharField(
        max_length=64,
        default="",
        blank=True,
        help_text="Inbound challenge/handshake (@webhook_challenge name). Blank: none.",
    )
    # Loop guard: when set to this SmallStack's own origin, inbound events carrying a
    # matching X-SmallStack-Origin header are dropped (a two-way S2S link can't echo).
    ignore_origin = models.CharField(
        max_length=200,
        default="",
        blank=True,
        help_text="Drop inbound events whose X-SmallStack-Origin equals this (self-origin loop guard).",
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhook_receivers",
        null=True,
        blank=True,
    )

    last_received_at = models.DateTimeField(null=True, blank=True)
    total_received = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Webhook Receiver"
        verbose_name_plural = "Webhook Receivers"

    def __str__(self) -> str:
        return self.name

    @property
    def handler_name(self) -> str:
        return self.handler or self.slug

    @property
    def secret_preview(self) -> str:
        if not self.secret:
            return "—"
        return f"{self.secret[:SECRET_PREVIEW_LEN]}…"


class WebhookReceipt(models.Model):
    """Append-only record of one POST to an inbound receiver."""

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"  # signature ok, queued for dispatch
        REJECTED = "rejected", "Rejected"  # signature failed / receiver disabled
        PROCESSED = "processed", "Processed"  # handler ran successfully
        FAILED = "failed", "Failed"  # handler raised
        IGNORED = "ignored", "Ignored"  # dropped (self-origin loop guard / challenge)

    receiver = models.ForeignKey(
        WebhookReceiver, on_delete=models.CASCADE, related_name="receipts"
    )
    received_at = models.DateTimeField(auto_now_add=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    body = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    # X-SmallStack-Origin of the sender (blank for non-SmallStack senders). Recorded so a
    # receiver can drop self-originated events and an operator can trace a loop.
    origin = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACCEPTED, db_index=True
    )
    task_result_id = models.CharField(max_length=64, blank=True, db_index=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Webhook Receipt"
        verbose_name_plural = "Webhook Receipts"
        indexes = [models.Index(fields=["receiver", "-received_at"])]

    def __str__(self) -> str:
        return f"{self.receiver_id} · {self.status} @ {self.received_at:%Y-%m-%d %H:%M}"

    @property
    def receiver_name(self) -> str:
        return self.receiver.name

    def json(self) -> Any:
        """Parsed request body (dict/list/scalar), or None if it isn't JSON."""
        import json

        try:
            return json.loads(self.body)
        except (ValueError, TypeError):
            return None
