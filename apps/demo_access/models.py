"""Scenario C models — a time-bound elevated-access grant, filed over REST.

``state`` and ``granted_until`` are written ONLY by the ``access.grant`` kind
callback. The grant is the armed thing: it exists on approval and on nothing
else.

``WebhookEcho`` is the local receiver's inbox — a place the tester can look to
confirm that the outbound `smallstack_approvals.approvalrequest.*` events
actually arrived somewhere (see webhook_handlers.py).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AccessRequest(models.Model):
    class Scope(models.TextChoices):
        READ = "read", "Read"
        WRITE = "write", "Write"
        ADMIN = "admin", "Admin"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        GRANTED = "granted", "Granted"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"
        CANCELED = "canceled", "Canceled"

    # e.g. "dataset:payroll", "vault:prod-db"
    resource = models.CharField(max_length=120, db_index=True)
    scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.READ)
    reason = models.TextField(blank=True, default="")
    duration_hours = models.PositiveIntegerField(default=8)

    state = models.CharField(
        max_length=10, choices=State.choices, default=State.PENDING, db_index=True
    )
    approval = models.ForeignKey(
        "smallstack_approvals.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_requests",
    )
    # Set ONLY on approval — the time bound on the grant.
    granted_until = models.DateTimeField(null=True, blank=True)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="access_requests",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Access request"

    def __str__(self) -> str:
        return f"{self.resource} ({self.scope})"

    @property
    def is_active_grant(self) -> bool:
        """A granted row whose time bound has not passed yet."""
        return bool(
            self.state == self.State.GRANTED
            and self.granted_until
            and self.granted_until > timezone.now()
        )


class WebhookEcho(models.Model):
    """One row per approval webhook this instance delivered to itself.

    Written by the ``access-grants`` inbound handler, so the tester has a
    readable record of the `.created` / `.updated` fan-out instead of digging
    through raw receipts.
    """

    event_type = models.CharField(max_length=200, db_index=True)
    approval_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "Webhook echo"
        verbose_name_plural = "Webhook echoes"

    def __str__(self) -> str:
        return f"{self.event_type} → {self.status or '?'}"
