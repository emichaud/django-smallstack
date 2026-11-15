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
    # Refused when deciding (G1-3); the callback refuses too, as a backstop.
    with pytest.raises(approvals.ApprovalRefused, match="names 'victim'"):
        approvals.approve(req, actor=root, source="web")
    req.refresh_from_db()
    assert req.status == "pending"
    from apps.access.approvals import on_membership_decision

    req.status, req.decided_by = req.Status.APPROVED, root
    with pytest.raises(ValueError, match="names 'victim'"):
        on_membership_decision(req)
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
    # G1-3: the refusal reaches the approver when deciding; the request stays pending.
    with pytest.raises(approvals.ApprovalRefused, match="auth.change_group"):
        approvals.approve(req, actor=um, source="web")
    req.refresh_from_db()
    assert req.status == "pending"
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
    # Reading needs view_user (the staffer fixture holds it); the page is read-only.
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


# --- A4: Django admin's user form ---------------------------------------------------


def _admin_change(client, target, **extra):
    data = {
        "username": target.username,
        "first_name": "",
        "last_name": "",
        "email": target.email or "",
        "is_active": "on",
        "is_staff": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
        "initial-date_joined_0": "2026-01-01",
        "initial-date_joined_1": "00:00:00",
    }
    data.update(extra)
    return client.post(f"/admin/accounts/user/{target.pk}/change/", data)


def test_a4_a_change_user_holder_cannot_make_themselves_superuser_in_admin(client, um, powerful):
    client.force_login(um)
    page = client.get(f"/admin/accounts/user/{um.pk}/change/").content.decode()
    assert 'name="is_superuser"' not in page and 'name="groups"' not in page
    assert 'name="user_permissions"' not in page
    resp = _admin_change(
        client, um, is_superuser="on", groups=[powerful.pk], user_permissions=[perm("auth.change_group").pk]
    )
    assert resp.status_code == 302
    um.refresh_from_db()
    assert not um.is_superuser and not um.groups.exists()
    assert not um.user_permissions.filter(codename="change_group").exists()
    assert um.user_permissions.filter(codename="change_user").exists()  # kept, not wiped


def test_a4_a_superuser_still_edits_those_fields(client, root, alice, readers):
    client.force_login(root)
    page = client.get(f"/admin/accounts/user/{alice.pk}/change/").content.decode()
    assert 'name="is_superuser"' in page and 'name="groups"' in page


def test_a4_sensitive_admins_always_check_model_permissions_in_explorer(settings):
    from django.contrib import admin

    from apps.access.models import AccessEvent, ManagedGroup
    from apps.explorer.registry import explorer_uses_model_permissions

    settings.SMALLSTACK_EXPLORER_MODEL_PERMISSIONS = False
    for model in (User, AccessEvent, ManagedGroup):
        assert explorer_uses_model_permissions(type(admin.site._registry[model])), model


# --- A5: the first migrate leaves declared groups complete -----------------------


def test_a5_a_fresh_database_has_every_shipped_group_with_all_its_permissions():
    """The pytest DB is built by one migrate: the same as a first deploy."""
    from apps.access.models import ManagedGroup
    from apps.access.registry import declared_groups

    for spec in declared_groups():
        group = Group.objects.get(name=spec.name)
        held = {f"{p.content_type.app_label}.{p.codename}" for p in group.permissions.select_related("content_type")}
        assert set(spec.permissions) <= held, spec.name
        assert ManagedGroup.objects.get(group=group).drift()["missing"] == []
    approver = Group.objects.get(name="Approver")
    assert approver.permissions.count() == 2


def test_a5_a_declared_permission_that_does_not_exist_shows_as_missing_drift(monkeypatch):
    from apps.access import registry
    from apps.access.models import ManagedGroup
    from apps.access.registry import register_group, sync_groups

    monkeypatch.setattr(registry, "_groups", {})
    register_group("Typo", permissions=["accounts.view_user", "nope.nothing"])
    sync_groups(source="test")
    managed = ManagedGroup.objects.get(group__name="Typo")
    assert "nope.nothing" in managed.declared_permissions
    assert managed.drift() == {"added": [], "missing": ["nope.nothing"]}


# --- A6: odd ids are 404s, not 500s ---------------------------------------------------


def test_a6_superscript_digits_are_a_404_on_rest(client, staffer):
    h = bearer(staffer, "staff")
    assert client.get("/smallstack/api/access/users/%C2%B2/", **h).status_code == 404
    assert client.get("/smallstack/api/access/groups/%C2%B2/", **h).status_code == 404


def test_a6_a_non_numeric_id_on_the_membership_forms_is_a_404(client, um, alice, readers):
    client.force_login(um)
    members = f"/smallstack/access/groups/{readers.pk}/members/"
    assert client.post(members, {"user": "abc", "action": "add"}).status_code == 404
    groups = f"/smallstack/access/users/{alice.pk}/groups/"
    assert client.post(groups, {"group": "²", "action": "add"}).status_code == 404


# --- A7: no open redirect from the members form ---------------------------------------


@pytest.mark.parametrize("target", ["https://evil.example/x", "//evil.example/x", "javascript:alert(1)"])
def test_a7_next_must_be_a_same_site_path(client, um, alice, readers, target):
    client.force_login(um)
    resp = client.post(
        f"/smallstack/access/groups/{readers.pk}/members/", {"user": alice.pk, "action": "add", "next": target}
    )
    assert resp.status_code == 302 and resp["Location"] == f"/smallstack/access/groups/{readers.pk}/"
    assert alice.groups.filter(pk=readers.pk).exists()
    ok = client.post(
        f"/smallstack/access/groups/{readers.pk}/members/",
        {"user": alice.pk, "action": "remove", "next": "/smallstack/access/"},
    )
    assert ok["Location"] == "/smallstack/access/"


# --- A8: CSV exports neutralise formulas -------------------------------------------------


def test_a8_csv_exports_neutralise_formula_cells(client, staffer):
    User.objects.create_user("+1+evil", password="p", email="=cmd@example.com")
    Group.objects.create(name='=HYPERLINK("http://evil.example/","x")')
    client.force_login(staffer)
    matrix = b"".join(client.get("/smallstack/access/export/access.csv").streaming_content).decode()
    events = b"".join(client.get("/smallstack/access/events.csv").streaming_content).decode()
    for body in (matrix, events):
        for line in body.splitlines():
            for cell in line.split(","):
                assert not cell.lstrip('"').startswith(("=", "+", "@")), line
    assert "'+1+evil" in matrix and "'=HYPERLINK" in events


# --- A9: deleted accounts and groups keep their names on the record --------------------


def test_a9_deletions_are_found_by_name_in_the_change_log(client, staffer):
    from apps.access.models import AccessEvent

    gone = User.objects.create_user("gone_user", password="p")
    gone.delete()
    Group.objects.create(name="gone_group").delete()
    assert AccessEvent.objects.get(kind="user_deleted").subject_label == "gone_user"
    assert AccessEvent.objects.get(kind="group_deleted").group_label == "gone_group"
    client.force_login(staffer)
    body = client.get("/smallstack/access/events.csv?who=gone_").getvalue().decode()
    assert "user_deleted" in body and "group_deleted" in body


# --- A10: the audit gaps ---------------------------------------------------------------


def test_a10_reverse_side_permission_changes_are_recorded(alice, readers):
    from apps.access.models import AccessEvent

    p = perm("auth.change_group")
    p.user_set.add(alice)
    p.group_set.add(readers)
    assert AccessEvent.objects.filter(kind="permission_added", subject=alice, permission="auth.change_group").exists()
    assert AccessEvent.objects.filter(
        kind="group_permission_added", group=readers, permission="auth.change_group"
    ).exists()
    p.user_set.remove(alice)
    assert AccessEvent.objects.filter(kind="permission_removed", subject=alice, permission="auth.change_group").exists()


def test_a10_rename_and_members_of_a_deleted_group_are_recorded(alice, readers):
    from apps.access.models import AccessEvent

    alice.groups.add(readers)
    readers.name = "Renamed readers"
    readers.save()
    renamed = AccessEvent.objects.get(kind="group_renamed")
    assert renamed.detail == {"from": "Readers", "to": "Renamed readers"}
    readers.delete()
    removed = AccessEvent.objects.get(kind="group_removed", subject=alice)
    assert removed.group_label == "Renamed readers"


def test_a10_an_audit_failure_does_not_lose_the_callers_change(alice):
    from django.db import transaction

    from apps.access.record import record

    with transaction.atomic():
        alice.first_name = "Kept"
        alice.save()
        assert record("group_added", subject=alice, detail={"bad": object()}) is None
        alice.last_name = "Also kept"
        alice.save()
    alice.refresh_from_db()
    assert (alice.first_name, alice.last_name) == ("Kept", "Also kept")


# --- A11: the review says what is true ------------------------------------------------


def test_a11_token_finding_counts_only_tokens_that_can_manage_accounts(um, alice, staffer):
    from apps.access.checks import system_tokens

    for owner in (um, alice, staffer):
        APIToken.create_token(user=owner, name=f"{owner.username}-auth", access_level="auth")
    finding = system_tokens()
    assert finding.count == 3
    assert "1 can manage accounts" in finding.summary


def test_a11_dormancy_all_clear_does_not_claim_never_signed_in_accounts_signed_in(alice, staffer):
    from apps.access.checks import dormant_accounts, dormant_privileged

    assert alice.last_login is None
    member = dormant_accounts()
    assert member.count == 0 and "signed in within" not in member.summary
    assert "never signed in" in member.summary
    privileged = dormant_privileged()
    assert "signed in within" not in privileged.summary and "never signed in" in privileged.summary


# --- A13: request_approval's polling instruction names a real field -------------------


def test_a13_request_approval_polls_on_a_field_get_approval_returns(staffer):
    from apps.mcp.server import TOOL_REGISTRY

    description = TOOL_REGISTRY["request_approval"].description
    req = approvals.request_approval(kind="x.y", title="t", actor=staffer)
    polled = run_tool("get_approval", {"id": req.pk}, user=staffer)
    assert "terminal" not in polled and "'terminal'" not in description
    assert "'status' is no longer 'pending'" in description and polled["status"] == "pending"
