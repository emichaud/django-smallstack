"""Scenario B — the app-owned half of the agent-action gate.

Pins: the can_decide narrowing on risk, exactly-once execution, the two distinct
failure paths (action failure vs a callback that raises), and "never executes on
a non-approval".
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.approvals import permissions as approval_perms
from apps.approvals import services as approvals
from apps.demo_agentops import services as agentops
from apps.demo_agentops.actions import RAISE_IN_CALLBACK_KEY
from apps.demo_agentops.models import AgentAction

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def agent():
    return User.objects.create_user("b-agent", password="p")


@pytest.fixture
def staff():
    """Staff but NOT superuser — refused on high risk."""
    return User.objects.create_user("b-staff", password="p", is_staff=True)


@pytest.fixture
def root():
    return User.objects.create_superuser("b-root", password="p")


def propose(agent, risk="low", tool_name="runbook.execute", payload=None):
    return agentops.propose(
        tool_name=tool_name,
        payload=payload if payload is not None else {"slug": "restart-web"},
        risk=risk,
        actor=agent,
        agent="test-agent",
        source="test",
    )


def test_propose_leaves_the_action_pending_and_unexecuted(agent):
    action, req = propose(agent)
    assert (action.state, action.result, action.executed_at) == ("pending", "", None)
    assert req.status == "pending"
    assert req.target == action
    assert req.expires_at is not None
    assert timedelta(minutes=28) < req.expires_at - timezone.now() <= timedelta(minutes=30)


def test_propose_rejects_an_unknown_risk(agent):
    with pytest.raises(ValueError):
        propose(agent, risk="catastrophic")


def test_high_risk_narrows_to_superusers(agent, staff, root):
    _, req = propose(agent, risk="high", tool_name="records.purge", payload={"count": 1})
    assert approval_perms.can_decide(staff, req) is False
    assert approval_perms.can_decide(root, req) is True


def test_the_hook_does_not_over_narrow_low_and_medium_risk(agent, staff):
    for risk in ("low", "medium"):
        _, req = propose(agent, risk=risk, tool_name="broadcast.send", payload={"audience": "x"})
        assert approval_perms.can_decide(staff, req) is True, risk


def test_the_hook_cannot_widen_past_the_staff_gate(agent):
    """can_decide returns True for low risk, but a bystander still can't decide."""
    bystander = User.objects.create_user("b-bystander", password="p")
    _, req = propose(agent, risk="low")
    assert approval_perms.can_decide(bystander, req) is False


def test_approval_executes_the_action_once(agent, staff):
    action, req = propose(agent)
    approvals.approve(req, actor=staff)
    action.refresh_from_db()
    assert action.state == AgentAction.State.EXECUTED
    assert action.result == "executed runbook restart-web"
    first = action.executed_at

    # A retried decision loses the race cleanly and does not re-run the action.
    with pytest.raises(approvals.NotPending):
        approvals.approve(req, actor=staff)
    action.refresh_from_db()
    assert action.executed_at == first


def test_a_failing_action_is_recorded_as_failed_without_a_callback_error(agent, staff):
    action, req = propose(agent, tool_name="records.purge", payload={"count": "nope"})
    approvals.approve(req, actor=staff)
    action.refresh_from_db()
    req.refresh_from_db()
    assert action.state == AgentAction.State.FAILED
    assert "count" in action.result
    assert req.status == "approved"  # the decision stands
    assert req.callback_error == ""  # handled by the app, not a framework fault


def test_an_unknown_tool_is_an_app_level_failure(agent, staff):
    action = AgentAction.objects.create(tool_name="nope.nope", risk="low", state="proposed")
    req = approvals.request_approval(
        kind="agentops.action", title="unknown tool", actor=agent, target=action
    )
    action.approval = req
    action.state = AgentAction.State.PENDING
    action.save()
    approvals.approve(req, actor=staff)
    action.refresh_from_db()
    assert action.state == AgentAction.State.FAILED
    assert "No handler" in action.result


def test_a_raising_callback_lands_in_callback_error_and_the_decision_stands(agent, staff):
    _, req = propose(agent, payload={"slug": "x", RAISE_IN_CALLBACK_KEY: True})
    approvals.approve(req, actor=staff)
    req.refresh_from_db()
    assert req.status == "approved"
    assert "deliberate callback failure" in req.callback_error


@pytest.mark.parametrize(
    "transition,expected",
    [
        ("reject", AgentAction.State.REJECTED),
        ("cancel", AgentAction.State.CANCELED),
    ],
)
def test_non_approval_never_executes(agent, staff, transition, expected):
    action, req = propose(agent)
    if transition == "reject":
        approvals.reject(req, actor=staff)
    else:
        approvals.cancel(req, actor=agent)
    action.refresh_from_db()
    assert (action.state, action.executed_at) == (expected, None)
    assert "not executed" in action.result


def test_expiry_never_executes(agent):
    action, req = propose(agent)
    req.expires_at = timezone.now() - timedelta(minutes=1)
    req.save(update_fields=["expires_at"])
    assert approvals.mark_expired() == 1
    action.refresh_from_db()
    assert (action.state, action.executed_at) == (AgentAction.State.EXPIRED, None)


def test_the_mcp_tool_is_registered_for_any_token_tier():
    import apps.demo_agentops.mcp_tools  # noqa: F401 — registers on import
    from apps.mcp.server import TOOL_REGISTRY

    spec = TOOL_REGISTRY["propose_agent_action"]
    assert spec.write is True
    assert spec.requires_access is None
    # The description has to tell a model how to close the loop unaided.
    assert "get_approval" in spec.description
