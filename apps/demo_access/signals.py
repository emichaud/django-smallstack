"""Scenario C signal receiver — the remote-reaction log.

Connected by ``DemoAccessConfig.ready()``. The grant itself is written by the
kind callback; this only records that the decision was observable on the signal
seam as well, which is what a service without webhook access would use.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver

from apps.approvals.signals import approval_decided

from .approvals import KIND

logger = logging.getLogger("smallstack.demo_access")


@receiver(approval_decided, dispatch_uid="demo_access_log_decision")
def log_access_decision(
    sender: Any, request: Any, actor: Any, source: str, **kwargs: Any
) -> None:
    if request.kind != KIND:
        return
    ar = request.target
    logger.info(
        "access decision: approval=%s status=%s source=%s actor=%s granted_until=%s",
        request.pk,
        request.status,
        source,
        getattr(actor, "username", "-"),
        getattr(ar, "granted_until", None) or "-",
    )
