"""Regressions for the 2026-11-14 access-control round (Coder A: A1-A15).

Each test names the finding it pins; each failed on e385789."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from apps.approvals import services as approvals
from apps.approvals.models import ApprovalRequest
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()


def bearer(user, level="auth"):
    _token, raw = APIToken.create_token(user=user, name=f"t-{level}", access_level=level)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def run_tool(name, args, *, user):
    from apps.mcp.server import TOOL_HANDLERS, ToolContext, reset_context, set_context

    token = set_context(ToolContext(user=user, token=None))
    try:
        return TOOL_HANDLERS[name](args)
    finally:
        reset_context(token)


def perm(label):
    app, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def member(db):
    """A self-registered account: no staff flag, no permissions."""
    return User.objects.create_user("member", password="p")


@pytest.fixture
def victim(db):
    return User.objects.create_user("victim", password="p")


@pytest.fixture
def powerful(db):
    group = Group.objects.create(name="Powerful")
    group.permissions.add(perm("accounts.change_user"), perm("auth.change_group"))
    return group


# --- A1: a forged access.membership approval -------------------------------------


FORGED = {
    "kind": "access.membership",
    "title": "Add victim to Powerful",
    "context": {"username": "victim", "group": "Powerful", "member": True, "group_permissions": 1},
}


def test_a1_generic_rest_create_refuses_the_access_kind(client, member, powerful):
    payload = dict(FORGED, target=f"accounts.user:{member.pk}")
    resp = client.post(
        "/smallstack/api/approvals/requests/create/",
        data=payload,
        content_type="application/json",
        **bearer(member),
    )
    assert resp.status_code == 403
    assert "own app" in resp.json()["errors"]["__all__"][0]
    assert not ApprovalRequest.objects.filter(kind="access.membership").exists()


def test_a1_generic_mcp_request_approval_refuses_the_access_kind(member, powerful):
    reply = run_tool("request_approval", dict(FORGED, target=f"accounts.user:{member.pk}"), user=member)
    assert reply["error"]["code"] == "not_permitted"
    assert not ApprovalRequest.objects.filter(kind="access.membership").exists()


def test_a1_a_forged_row_is_refused_at_decision_and_the_card_names_the_real_account(
    client, root, member, victim, powerful
):
    # Filed in-process (bypassing the remote refusal) the way the old routes did.
    req = approvals.request_approval(
        kind="access.membership",
        title=FORGED["title"],
        actor=member,
        context=FORGED["context"],
        target=member,
    )
    client.force_login(root)
    page = client.get(f"/smallstack/approvals/requests/{req.pk}/").content.decode()
    assert "would change &#x27;member&#x27;" in page or "would change 'member'" in page
    assert "Add <strong>victim</strong>" not in page
    approvals.approve(req, actor=root, source="web")
    req.refresh_from_db()
    assert "names 'victim'" in req.callback_error
    assert not member.groups.exists() and not victim.groups.exists()


def test_a1_the_card_reads_the_group_from_the_database(client, root, alice, readers):
    from apps.access.approvals import request_membership_change

    req = request_membership_change(alice, readers, True, actor=root, reason="r")
    ApprovalRequest.objects.filter(pk=req.pk).update(
        context={**req.context, "group_permissions": 0}
    )
    client.force_login(root)
    page = client.get(f"/smallstack/approvals/requests/{req.pk}/").content.decode()
    assert "Add <strong>alice</strong> to the group <strong>Readers</strong>" in page
    assert "(1 permission)" in page
