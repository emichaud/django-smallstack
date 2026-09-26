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


class ApprovalRequestQuerySet(models.QuerySet):
    """One definition of "pending right now", shared by every reader.

    Expiry is lazy (§6), so ``status="pending"`` and *actually awaiting a human*
    are not the same set: a row whose ``expires_at`` has passed is still
    ``pending`` in the database until something sweeps it. Every surface that
    counts or lists the queue must use the same definition or the numbers
    disagree (the dashboard widget said 7 while the queue said 4 — F-19).
    """

    def pending(self) -> "ApprovalRequestQuerySet":
        """Rows whose stored status is pending, overdue ones included."""
        return self.filter(status=ApprovalRequest.Status.PENDING)

    def overdue(self, now: Any = None) -> "ApprovalRequestQuerySet":
        """Pending rows past their expiry — what a sweep would flip."""
        return self.pending().filter(
            expires_at__isnull=False, expires_at__lte=now or timezone.now()
        )

    def actionable(self, now: Any = None) -> "ApprovalRequestQuerySet":
        """Pending rows a human can still decide — pending minus overdue.

        Cheap (one query, no fan-out): safe for dashboards and stat cards.
        """
        return self.pending().exclude(
            expires_at__isnull=False, expires_at__lte=now or timezone.now()
        )

    def for_effective_status(self, value: str, now: Any = None) -> "ApprovalRequestQuerySet":
        """Rows whose *effective* status is ``value`` — the single definition.

        The stored ``status`` column is not the effective status while expiry is
        lazy: an overdue row reads ``pending`` until a sweep flips it. Every
        surface that counts, lists or filters by status goes through here, so the
        stat card, the ``?status=`` filter (HTML + REST + MCP) and the row badge
        cannot disagree — which they did, by 900 rows on one page (F-29).

        ``pending`` → :meth:`actionable`; ``expired`` → stored-expired **plus**
        :meth:`overdue`; anything else → the stored column.
        """
        from django.db.models import Q

        if value == ApprovalRequest.Status.PENDING:
            return self.actionable(now=now)
        if value == ApprovalRequest.Status.EXPIRED:
            return self.filter(
                Q(status=ApprovalRequest.Status.EXPIRED)
                | Q(pk__in=self.overdue(now=now).values("pk"))
            )
        return self.filter(status=value)


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

    objects = ApprovalRequestQuerySet.as_manager()

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
    def effective_status(self) -> str:
        """The status a human should be shown — row-level twin of
        :meth:`ApprovalRequestQuerySet.for_effective_status`.

        An overdue row's stored ``status`` still reads ``pending`` until a sweep
        flips it, so a queue badge rendered straight from the column told the
        approver a row was theirs to decide when it was not. (F-29.)
        """
        if self.is_overdue:
            return str(self.Status.EXPIRED)
        return str(self.status)

    @property
    def effective_status_display(self) -> str:
        """Human label for :attr:`effective_status`."""
        return dict(self.Status.choices).get(self.effective_status, self.effective_status)

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

    @property
    def target_ref(self) -> str | None:
        """The target as ``"app_label.model:pk"`` — the same spelling REST and
        MCP *accept* when filing, so a remote client can read back what it sent.

        ``target`` (above) resolves to the instance and is the Python-side API a
        kind callback uses; it serializes to ``null`` on the wire, which left a
        client able to set a target and able to render ``target_repr`` for a
        human, but unable to link back to the row or re-derive which object it
        was — the duplication the target pointer existed to remove. (F-35.)
        """
        ct = self.target_content_type
        if ct is None or not self.target_object_id:
            return None
        return f"{ct.app_label}.{ct.model}:{self.target_object_id}"

    @property
    def assignee_usernames(self) -> list[str]:
        """Assignees as usernames — the M2M is invisible to the wire otherwise."""
        return [u.username for u in self.assignees.all()]

    def set_target(self, obj: models.Model | None) -> None:
        if obj is None:
            self.target_content_type = None
            self.target_object_id = ""
            self.target_repr = ""
            return
        self.target_content_type = ContentType.objects.get_for_model(obj)
        self.target_object_id = str(obj.pk)
        self.target_repr = str(obj)[:200]
