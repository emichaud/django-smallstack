"""Approval domain signals — the in-process extension seam (runbook pattern).

Emitted by the service layer on ``transaction.on_commit``, so a rolled-back
write never fires consumers.

- ``approval_requested`` — kwargs: ``request`` (the ApprovalRequest),
  ``actor``.
- ``approval_decided`` — fires for EVERY terminal transition (approved,
  rejected, canceled, expired; read ``request.status``). kwargs: ``request``,
  ``actor`` (None for expiry), ``source``.
"""

from __future__ import annotations

from django.dispatch import Signal

approval_requested = Signal()
approval_decided = Signal()
