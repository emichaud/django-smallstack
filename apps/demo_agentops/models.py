"""Scenario B model — a privileged action an AI agent wants to run.

The row is the audit trail of what agents proposed; ``state`` / ``result`` /
``executed_at`` are written ONLY by the ``agentops.action`` kind callback (plus
``state=PENDING`` when the approval is filed, in ``services.propose``). The
action itself never runs until a human approves.
"""

from __future__ import annotations

from django.db import models


class AgentAction(models.Model):
    class Risk(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    class State(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        PENDING = "pending", "Pending"
        EXECUTED = "executed", "Executed"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        CANCELED = "canceled", "Canceled"
        FAILED = "failed", "Failed"

    # e.g. "broadcast.send", "records.purge", "runbook.execute"
    tool_name = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    risk = models.CharField(max_length=10, choices=Risk.choices, default=Risk.MEDIUM, db_index=True)
    # Which agent / token asked. Free-form label, not a FK: the caller is an
    # agent identity, and the human user behind the token is on the approval.
    requested_by_agent = models.CharField(max_length=100, blank=True, default="")

    state = models.CharField(
        max_length=10, choices=State.choices, default=State.PROPOSED, db_index=True
    )
    approval = models.ForeignKey(
        "smallstack_approvals.ApprovalRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_actions",
    )
    result = models.TextField(blank=True, default="")
    executed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Agent action"

    def __str__(self) -> str:
        return f"{self.tool_name} [{self.risk}]"

    @property
    def is_executed(self) -> bool:
        return self.state == self.State.EXECUTED

    @property
    def needs_superuser(self) -> bool:
        """High-risk actions narrow eligibility to superusers (see approvals.py)."""
        return self.risk == self.Risk.HIGH
