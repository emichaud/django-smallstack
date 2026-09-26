"""Scenario A model — a purchase request that a human has to say yes to.

The approvals app never writes this model: ``state`` / ``po_number`` /
``decided_note`` are written ONLY by the ``purchasing.approve`` kind callback in
``approvals.py`` (plus ``state=PENDING`` when the request is filed, in
``services.submit_for_approval``). That split is the whole point of the
side-car gate: what "approved" *means* stays app-owned.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

# Requests at or above this amount route to the finance approvers group (a
# NON-staff group in the demo) instead of "any staff member".
HIGH_VALUE_THRESHOLD = Decimal("5000")

# Django Group whose members are the tier-2 (finance) approvers. Created by
# `manage.py seed_approval_scenarios`.
FINANCE_GROUP = "finance-approvers"


class PurchaseRequest(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        CANCELED = "canceled", "Canceled"

    class Category(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        SOFTWARE = "software", "Software"
        SERVICES = "services", "Services"
        TRAVEL = "travel", "Travel"

    vendor = models.CharField(max_length=120)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.HARDWARE)
    justification = models.TextField(blank=True, default="")

    state = models.CharField(
        max_length=10, choices=State.choices, default=State.DRAFT, db_index=True
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    # The link back to the side-car gate. Null while the row is a draft.
    approval = models.ForeignKey(
        "smallstack_approvals.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="purchase_requests",
    )
    decided_note = models.TextField(blank=True, default="")
    # Set ONLY on approval — the proof that the kind callback actually ran.
    po_number = models.CharField(max_length=32, blank=True, default="", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Purchase request"

    def __str__(self) -> str:
        return f"{self.description} — {self.vendor} (${self.amount})"

    @property
    def is_high_value(self) -> bool:
        """True when this request routes to the finance approvers (tier 2)."""
        return self.amount >= HIGH_VALUE_THRESHOLD

    @property
    def tier(self) -> str:
        return "finance" if self.is_high_value else "any-staff"

    @property
    def can_submit(self) -> bool:
        return self.state == self.State.DRAFT

    def mint_po_number(self) -> str:
        """Deterministic PO number — stable across reseeds and screenshots."""
        return f"PO-{self.pk:05d}"
