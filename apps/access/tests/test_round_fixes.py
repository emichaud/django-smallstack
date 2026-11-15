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


# --- A2: a User manager can't hand out (or take) more than they hold ---------------


@pytest.fixture
def um(db):
    """Staff + the shipped User manager permissions, nothing more."""
    user = User.objects.create_user("um", password="p", is_staff=True)
    user.user_permissions.add(perm("accounts.change_user"), perm("accounts.view_user"))
    return user


def test_a2_service_refuses_adding_to_a_group_with_permissions_the_actor_lacks(um, alice, powerful):
    from apps.access import services

    with pytest.raises(services.MembershipRefused, match="auth.change_group"):
        services.set_membership(um, powerful, True, actor=um, source="test")
    with pytest.raises(services.MembershipRefused):
        services.set_membership(alice, powerful, True, actor=um, source="test")
    assert not powerful.user_set.exists()
    # Removal is still allowed.
    alice.groups.add(powerful)
    assert services.set_membership(alice, powerful, False, actor=um, source="test") is True


def test_a2_a_superuser_may_add_to_any_group(root, alice, powerful):
    from apps.access import services

    assert services.set_membership(alice, powerful, True, actor=root, source="test") is True


def test_a2_rest_and_web_refuse_with_the_missing_permission(client, um, alice, powerful):
    resp = client.put(f"/smallstack/api/access/users/alice/groups/{powerful.name}/", **bearer(um))
    assert resp.status_code == 403 and "auth.change_group" in resp.json()["errors"]["__all__"][0]
    client.force_login(um)
    resp = client.post(
        f"/smallstack/access/users/{alice.pk}/groups/", {"group": powerful.pk, "action": "add"}, follow=True
    )
    assert "auth.change_group" in resp.content.decode()
    assert not alice.groups.exists()


def test_a2_an_approval_applies_only_what_the_approver_could_do(staffer, um, alice, powerful):
    from apps.access.approvals import request_membership_change

    req = request_membership_change(alice, powerful, True, actor=staffer, reason="r")
    approvals.approve(req, actor=um, source="web")
    req.refresh_from_db()
    assert "auth.change_group" in req.callback_error
    assert not alice.groups.exists()


# --- A12: the CLI asks for staff too --------------------------------------------


def test_a12_cli_grant_refuses_a_non_staff_actor(alice, readers):
    from django.core.management import CommandError, call_command

    nonstaff = User.objects.create_user("nonstaff", password="p")
    nonstaff.user_permissions.add(perm("accounts.change_user"), perm("accounts.view_user"))
    with pytest.raises(CommandError, match="not staff"):
        call_command("access", "grant", "alice", "Readers", "--user", "nonstaff")
    assert not alice.groups.exists()


# --- A3: the User Manager's writes ask for the model permissions -------------------


def _um_edit(client, target, **fields):
    data = {
        "username": target.username,
        "email": target.email,
        "first_name": "",
        "last_name": "",
        "is_active": "on",
        "profile-timezone": "",
    }
    data.update(fields)
    return client.post(f"/smallstack/manage/users/{target.pk}/edit/", data)


def test_a3_plain_staff_cannot_write_through_the_user_manager(client, staffer, alice):
    client.force_login(staffer)
    # Reading stays a staff matter; the page is read-only.
    page = client.get(f"/smallstack/manage/users/{alice.pk}/edit/")
    assert page.status_code == 200
    body = page.content.decode()
    assert 'class="btn-save"' not in body and "Read-only" in body
    assert "+ Add User" not in client.get("/smallstack/manage/users/").content.decode()
    # Staff flag on, then deactivate: both refused.
    assert _um_edit(client, alice, is_staff="on").status_code == 403
    assert _um_edit(client, alice, is_active="").status_code == 403
    alice.refresh_from_db()
    assert alice.is_active and not alice.is_staff
    assert client.get("/smallstack/manage/users/new/").status_code == 403
    assert client.post(f"/smallstack/manage/users/{alice.pk}/delete/").status_code == 403
    assert client.post(f"/smallstack/manage/users/{alice.pk}/send-link/").status_code == 403
    assert client.post(f"/smallstack/manage/users/{alice.pk}/unlock/").status_code == 403
    assert User.objects.filter(pk=alice.pk).exists()


def test_a3_a_user_manager_edits_accounts_but_not_a_superusers(client, um, alice, root):
    client.force_login(um)
    assert _um_edit(client, alice, is_staff="on").status_code == 302
    alice.refresh_from_db()
    assert alice.is_staff
    assert _um_edit(client, root, email="evil@example.com", is_staff="on").status_code == 403
    root.refresh_from_db()
    assert root.email != "evil@example.com"
    # Deleting needs delete_user, which the User manager group doesn't grant.
    assert client.post(f"/smallstack/manage/users/{alice.pk}/delete/").status_code == 403
