"""Scenario B kind — ``agentops.action`` (autodiscovered by apps/approvals).

Two claims from docs/skills/approvals.md are load-bearing here:

* §3 — a kind's ``can_decide`` hook **ANDs** with the default policy: it can
  narrow ("high risk needs a superuser") but never widen. ``high_risk_needs_
  superuser`` returns True for everyone on low/medium risk, so the default
  staff/assignee gates are what still decide those.
* §4.1 — the callback "never breaks the decision"; a raised exception lands in
  ``callback_error``. The action's own failures are caught here and recorded as
  ``state=failed``; only the reserved ``RAISE_IN_CALLBACK_KEY`` flag is allowed
  to escape, so the tester can see the callback_error band for real.

Unlike Scenario A, this kind sets an explicit ``context_template`` (rather than
relying on the key-derived ``approvals/kinds/agentops-action.html``) so both
template-resolution paths from §5 are covered by the scenarios.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.approvals import approval_kind
from apps.approvals.models import ApprovalRequest

from .actions import RAISE_IN_CALLBACK_KEY, execute
from .models import AgentAction

logger = logging.getLogger("smallstack.demo_agentops")

KIND = "agentops.action"

_STATE_FOR_STATUS: dict[str, str] = {
    ApprovalRequest.Status.REJECTED: AgentAction.State.REJECTED,
    ApprovalRequest.Status.CANCELED: AgentAction.State.CANCELED,
    ApprovalRequest.Status.EXPIRED: AgentAction.State.EXPIRED,
}


def high_risk_needs_superuser(user: Any, req: Any) -> bool:
    """Eligibility hook: high-risk actions need ``is_superuser``.

    Reads the risk off the target when it exists and falls back to the stored
    context, so the narrowing still applies to a row whose AgentAction was
    deleted. A hook that raises fails CLOSED (approvals/permissions.py), so
    everything here is defensive on purpose.
    """
    action = req.target
    risk = getattr(action, "risk", None) or (req.context or {}).get("risk")
    if risk == AgentAction.Risk.HIGH:
        return bool(getattr(user, "is_superuser", False))
    return True


@approval_kind(
    KIND,
    label="Approve agent action",
    description=(
        "Human-in-the-loop gate for AI agent actions. Risk contract: low and "
        "medium risk may be decided by any eligible staff member; HIGH risk "
        "additionally requires a superuser. Approval executes the action "
        "exactly once; every other outcome leaves it unexecuted."
    ),
    can_decide=high_risk_needs_superuser,
    default_expires_in=timedelta(minutes=30),
    context_template="demo_agentops/approval_card.html",
)
def on_action_decision(req: Any) -> None:
    """React to ANY terminal transition of an agentops.action request."""
    action = req.target
    if not isinstance(action, AgentAction):
        return

    if req.status != ApprovalRequest.Status.APPROVED:
        state = _STATE_FOR_STATUS.get(req.status)
        if state is None:  # pragma: no cover — services only calls us post-terminal
            logger.warning("agentops.action: non-terminal status %r", req.status)
            return
        # Disarm: the action is never executed on a non-approval.
        action.state = state
        action.result = f"not executed ({req.get_status_display().lower()})"
        action.save(update_fields=["state", "result", "updated_at"])
        return

    if action.is_executed:
        # Exactly-once: a retried/duplicated decision must not re-run the action.
        return

    if (action.payload or {}).get(RAISE_IN_CALLBACK_KEY):
        # Deliberate demo of docs §4.1 — this escapes into callback_error and
        # the APPROVED decision still stands.
        raise RuntimeError("demo_agentops: deliberate callback failure")

    try:
        result = execute(action.tool_name, action.payload or {})
    except Exception as exc:  # noqa: BLE001 — an action failure is app state, not a crash
        logger.warning("agentops.action %s failed: %s", action.pk, exc)
        action.state = AgentAction.State.FAILED
        action.result = f"{type(exc).__name__}: {exc}"
        action.save(update_fields=["state", "result", "updated_at"])
        return

    action.state = AgentAction.State.EXECUTED
    action.result = result
    action.executed_at = timezone.now()
    action.save(update_fields=["state", "result", "executed_at", "updated_at"])
