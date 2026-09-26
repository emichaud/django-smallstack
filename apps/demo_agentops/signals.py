"""Scenario B signal receivers — observe the gate, never write the model.

Connected by ``DemoAgentOpsConfig.ready()``. These exist so an operator can grep
one logger to see the full agent loop (asked → decided) independently of the
callback that does the work.
"""

from __future__ import annotations

import logging
from typing import Any

from django.dispatch import receiver

from apps.approvals.signals import approval_decided, approval_requested

from .approvals import KIND

logger = logging.getLogger("smallstack.demo_agentops")


@receiver(approval_requested, dispatch_uid="demo_agentops_log_request")
def log_action_requested(sender: Any, request: Any, actor: Any, **kwargs: Any) -> None:
    if request.kind != KIND:
        return
    logger.info(
        "agent asked: approval=%s tool=%s risk=%s agent=%s",
        request.pk,
        (request.context or {}).get("tool_name", "-"),
        (request.context or {}).get("risk", "-"),
        (request.context or {}).get("agent", "-"),
    )


@receiver(approval_decided, dispatch_uid="demo_agentops_log_decision")
def log_action_decided(
    sender: Any, request: Any, actor: Any, source: str, **kwargs: Any
) -> None:
    if request.kind != KIND:
        return
    action = request.target
    logger.info(
        "agent action decided: approval=%s status=%s source=%s actor=%s state=%s",
        request.pk,
        request.status,
        source,
        getattr(actor, "username", "-"),
        getattr(action, "state", "-"),
    )
