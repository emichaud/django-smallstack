"""The ApprovalRequest model — one row per human decision needed.

State machine: pending → approved | rejected | canceled | expired. All
transitions go through ``services`` (race-safe conditional UPDATEs); nothing
else writes ``status`` / ``decided_*`` — the CRUD form and REST field lists
exclude them by design.

The target pointer is the house shape (audit.py): ContentType FK +
``target_object_id`` string + denormalized ``target_repr`` so a card can still
render after the target is deleted. ``target`` is a plain property, not a
GenericForeignKey (zero GFK precedent in this codebase).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone


class ApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELED = "canceled", "Canceled"
        EXPIRED = "expired", "Expired"

    # Registry key, e.g. "calendar.publish". Unregistered kinds are tolerated
    # (default card, no callback) so rows outlive code churn.
    kind = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    # Kind-specific payload rendered on the decision card.
    context = models.JSONField(default=dict, blank=True)

    target_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    target_object_id = models.CharField(max_length=64, blank=True, default="")
    target_repr = models.CharField(max_length=200, blank=True, default="")

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_requests_made",
    )
    # Optional: narrows who may decide. Empty ⇒ any staff (the default policy).
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="approval_requests_assigned"
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_requests_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    expires_at = models.DateTimeField(null=True, blank=True)
    # Observability: if the kind's on_decision callback raised, the traceback
    # summary lands here (the decision itself still stands).
    callback_error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Approval request"
        indexes = [
            models.Index(fields=["status", "created_at"], name="approvals_status_created"),
            models.Index(fields=["kind", "status"], name="approvals_kind_status"),
            models.Index(fields=["status", "expires_at"], name="approvals_expiry_sweep"),
        ]
        constraints = [
            models.CheckConstraint(
                name="approvals_pending_undecided",
                condition=Q(status="pending", decided_by__isnull=True, decided_at__isnull=True)
                | ~Q(status="pending"),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} [{self.get_status_display()}]"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.is_pending and self.expires_at and self.expires_at <= timezone.now()
        )

    @property
    def target(self) -> Any:
        """Resolve the target object; None when unset or deleted."""
        ct = self.target_content_type
        if ct is None or not self.target_object_id:
            return None
        try:
            return ct.get_object_for_this_type(pk=self.target_object_id)
        except Exception:  # noqa: BLE001 — deleted target, stale CT, bad pk
            return None

    def set_target(self, obj: models.Model | None) -> None:
        if obj is None:
            self.target_content_type = None
            self.target_object_id = ""
            self.target_repr = ""
            return
        self.target_content_type = ContentType.objects.get_for_model(obj)
        self.target_object_id = str(obj.pk)
        self.target_repr = str(obj)[:200]
