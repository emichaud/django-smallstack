"""Scenario A signal receiver — observing decisions WITHOUT writing the model.

docs/skills/approvals.md §4 lists five fan-outs for one decision. The callback
(approvals.py) owns the write; this receiver demonstrates the *observer* seam:
it only logs, so the two channels can be told apart when debugging. Connected by
``DemoPurchasingConfig.ready()`` importing this module.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver

from apps.approvals.signals import approval_decided

from .approvals import KIND

logger = logging.getLogger("smallstack.demo_purchasing")


@receiver(approval_decided, dispatch_uid="demo_purchasing_log_decision")
def log_purchase_decision(
    sender: Any, request: Any, actor: Any, source: str, **kwargs: Any
) -> None:
    """Log every purchasing decision (any terminal status, any surface)."""
    if request.kind != KIND:
        return
    pr = request.target
    logger.info(
        "purchase decision: approval=%s status=%s source=%s actor=%s po=%s",
        request.pk,
        request.status,
        source,
        getattr(actor, "username", "-"),
        getattr(pr, "po_number", "") or "-",
    )
