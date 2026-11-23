"""Directory-managed groups: a declaration carries a ``directory_role``, the
identity provider says at sign-in who holds which roles, ``sync_roles`` makes
the groups match, and nothing else may change them."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from apps.access import directory, registry, services
from apps.access.models import AccessEvent, DirectoryIdentity, ManagedGroup
from apps.access.registry import map_directory_role, register_group, run_checks, sync_groups
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def declarations(monkeypatch):
    """A clean registry with two directory-managed groups (one staff) and one local."""
    monkeypatch.setattr(registry, "_groups", {})
    monkeypatch.setattr(registry, "_role_overlays", {})
    register_group(
        "Service admins",
        permissions=["accounts.view_user", "accounts.change_user"],
        app_label="tests",
        directory_role="Service.Admin",
        staff=True,
    )
    register_group(
        "Event planners", permissions=["auth.view_group"], app_label="tests", directory_role="Events.Planner"
    )
    register_group("Local readers", permissions=["accounts.view_user"], app_label="tests")
    sync_groups(source="test")
    return {g.name: g for g in Group.objects.filter(name__in=["Service admins", "Event planners", "Local readers"])}


def finding(key):
    return next(f for f in run_checks() if f.key == key)


# --- Declaring -------------------------------------------------------------------


def test_the_declaration_is_stored_on_the_managed_group(declarations):
    admins = ManagedGroup.objects.get(group__name="Service admins")
    assert admins.directory_role == "Service.Admin" and admins.grants_staff and admins.directory_managed
    local = ManagedGroup.objects.get(group__name="Local readers")
    assert local.directory_role is None and not local.grants_staff and not local.directory_managed
    assert admins.as_dict()["directory_role"] == "Service.Admin"


def test_a_role_key_must_be_claim_safe(monkeypatch):
    monkeypatch.setattr(registry, "_groups", {})
    with pytest.raises(ValueError, match="no spaces"):
        register_group("Bad", permissions=[], directory_role="Service Admin")
    with pytest.raises(ValueError, match="no spaces"):
        map_directory_role("Bad", "x" * 101)


def test_two_groups_cannot_share_a_role(monkeypatch):
    monkeypatch.setattr(registry, "_groups", {})
    monkeypatch.setattr(registry, "_role_overlays", {})
    register_group("One", permissions=[], directory_role="Shared")
    with pytest.raises(ValueError, match="already declared"):
        register_group("Two", permissions=[], directory_role="Shared")
    register_group("Two", permissions=[])
    with pytest.raises(ValueError, match="already declared"):
        map_directory_role("Two", "Shared")


def test_map_directory_role_overlays_a_declaration_made_elsewhere(monkeypatch, caplog):
    """The shipped groups get a role from a downstream groups.py without their
    permission lists being copied, whatever the import order."""
    monkeypatch.setattr(registry, "_role_overlays", {})
    map_directory_role("Access reviewer", "Access.Reviewer")
    map_directory_role("Nobody declares this", "Nope")
    spec = next(g for g in registry.declared_groups() if g.name == "Access reviewer")
    assert spec.directory_role == "Access.Reviewer" and "access.view_accessevent" in spec.permissions
    summary = sync_groups(source="test")
    assert summary["unmatched_overlays"] == ["Nobody declares this"]
    assert "no declaration matches" in caplog.text
    assert ManagedGroup.objects.get(group__name="Access reviewer").directory_role == "Access.Reviewer"


# --- Identity ---------------------------------------------------------------------


def test_first_sight_creates_an_account_without_a_password(declarations):
    AccessEvent.objects.all().delete()
    identity = directory.resolve_identity("Entra", "oid-1", email="Ann@Example.com", name="Ann Lee")
    user = identity.user
    assert user.username == "ann@example.com" and user.email == "ann@example.com"
    assert (user.first_name, user.last_name) == ("Ann", "Lee")
    assert not user.has_usable_password() and not user.is_staff and not user.is_superuser
    assert identity.provider == "entra" and identity.email == "Ann@Example.com"
    created = AccessEvent.objects.get(kind="user_created")
    assert created.source == "directory:entra" and created.subject == user


def test_an_existing_account_is_linked_by_email_once_then_pinned_to_the_subject(declarations):
    alice = User.objects.create_user("alice", email="alice@example.com", password="p")
    identity = directory.resolve_identity("entra", "oid-alice", email="alice@example.com")
    assert identity.user == alice and User.objects.count() == 1
    # The mailbox is handed to someone else: the subject wins, no takeover.
    alice.email = "someone-else@example.com"
    alice.save()
    again = directory.resolve_identity("entra", "oid-alice", email="someone-else@example.com")
    assert again.pk == identity.pk and again.user == alice
    other = directory.resolve_identity("entra", "oid-new", email="alice@example.com")
    assert other.user != alice and other.user.email == "alice@example.com"
    assert directory.resolve_identity("entra", "unknown", create=False) is None


def test_linking_by_email_can_be_turned_off(declarations, settings):
    settings.SMALLSTACK_DIRECTORY_LINK_BY_EMAIL = False
    User.objects.create_user("alice", email="alice@example.com", password="p")
    identity = directory.resolve_identity("entra", "oid-x", email="alice@example.com")
    # A second account; the taken (unique) email isn't copied onto it.
    assert identity.user.username != "alice" and identity.user.email is None


def test_username_collisions_are_resolved(declarations):
    User.objects.create_user("bob@example.com", password="p")
    identity = directory.resolve_identity("okta", "s1", email="bob@example.com")
    assert identity.user.username == "bob@example.com2"


# --- The sync ---------------------------------------------------------------------


def test_sync_sets_exactly_the_directory_groups_and_leaves_local_ones(declarations):
    alice = User.objects.create_user("alice", password="p")
    alice.groups.add(declarations["Local readers"], declarations["Event planners"])
    AccessEvent.objects.all().delete()
    result = directory.sync_roles(alice, ["Service.Admin", " Service.Admin ", "Mystery.Role"], "entra")
    assert result.added == ["Service admins"] and result.removed == ["Event planners"]
    assert result.unknown == ["Mystery.Role"] and result.staff_granted and result.changed
    assert set(alice.groups.values_list("name", flat=True)) == {"Local readers", "Service admins"}
    alice.refresh_from_db()
    assert alice.is_staff and not alice.is_superuser
    sources = set(AccessEvent.objects.values_list("source", flat=True))
    assert sources == {"directory:entra"}
    assert set(AccessEvent.objects.values_list("kind", flat=True)) == {"group_added", "group_removed", "staff_on"}
    # Idempotent.
    assert not directory.sync_roles(alice, ["Service.Admin", "Mystery.Role"], "entra").changed


def test_an_empty_claim_strips_but_a_missing_claim_changes_nothing(declarations, caplog):
    alice = User.objects.create_user("alice", password="p", is_staff=True)
    alice.groups.add(declarations["Service admins"], declarations["Local readers"])
    skipped = directory.sync_roles(alice, None, "entra")
    assert skipped.skipped and not skipped.changed
    assert alice.groups.count() == 2 and "sent no roles claim" in caplog.text
    stripped = directory.sync_roles(alice, [], "entra")
    assert stripped.removed == ["Service admins"]
    assert list(alice.groups.values_list("name", flat=True)) == ["Local readers"]
    alice.refresh_from_db()
    assert alice.is_staff, "the sync never unsets staff"


def test_the_alias_map_translates_what_the_provider_sends(declarations, settings):
    settings.SMALLSTACK_DIRECTORY_ROLE_MAP = {"service-admins@example.com": "Service.Admin"}
    alice = User.objects.create_user("alice", password="p")
    result = directory.sync_roles(alice, ["service-admins@example.com"], "google")
    assert result.roles == ["Service.Admin"] and result.added == ["Service admins"] and not result.unknown


def test_sign_in_updates_the_identity(declarations):
    identity, result = directory.sign_in("entra", "oid-1", ["Events.Planner", "Odd"], email="a@example.com")
    identity.refresh_from_db()
    assert identity.last_roles == ["Events.Planner", "Odd"] and result.added == ["Event planners"]
    assert identity.last_seen_at >= identity.first_seen_at
    assert identity.user.groups.filter(name="Event planners").exists()


def test_sync_never_grants_superuser(declarations):
    alice = User.objects.create_user("alice", password="p")
    directory.sync_roles(alice, ["Service.Admin"], "entra")
    alice.refresh_from_db()
    assert not alice.is_superuser


# --- One source of truth -------------------------------------------------------------


def test_local_membership_changes_to_a_directory_group_are_refused(declarations, root, manager, alice):
    planners = declarations["Event planners"]
    with pytest.raises(services.MembershipRefused, match="comes from the directory"):
        services.set_membership(alice, planners, True, actor=root, source="test")
    with pytest.raises(services.MembershipRefused, match="Change it there"):
        services.set_membership(alice, planners, True, actor=None, source="cli")
    assert services.membership_refusal(manager, planners, False)
    assert not alice.groups.exists()
    # A local group is unaffected.
    assert services.set_membership(alice, declarations["Local readers"], True, actor=root, source="test")


def test_the_refusal_names_the_provider_once_one_has_signed_in(declarations, root, alice):
    directory.resolve_identity("entra", "oid-1")
    with pytest.raises(services.MembershipRefused, match="comes from entra"):
        services.set_membership(alice, declarations["Service admins"], True, actor=root, source="test")


def test_the_override_setting_lets_a_local_admin_through(declarations, root, alice, settings):
    settings.SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE = True
    assert services.set_membership(alice, declarations["Event planners"], True, actor=root, source="test")


def test_the_cli_refuses_too(declarations, alice):
    with pytest.raises(CommandError, match="comes from the directory"):
        call_command("access", "grant", "alice", "Event planners", stdout=StringIO())


def test_the_pages_hide_the_forms_and_say_where_membership_comes_from(declarations, client, root, alice):
    client.force_login(root)
    alice.groups.add(declarations["Event planners"], declarations["Local readers"])
    page = client.get(reverse("access:group_detail", kwargs={"pk": declarations["Event planners"].pk}))
    html = page.content.decode()
    assert "Membership comes from the directory" in html and "Events.Planner" in html
    assert 'name="action" value="add"' not in html and 'name="action" value="remove"' not in html
    local = client.get(reverse("access:group_detail", kwargs={"pk": declarations["Local readers"].pk})).content.decode()
    assert 'name="action" value="add"' in local
    user_page = client.get(reverse("access:user_detail", kwargs={"pk": alice.pk})).content.decode()
    # Remove is offered for the local group only; the directory group isn't in the add list.
    assert user_page.count('name="action" value="remove"') == 1
    assert f'<option value="{declarations["Service admins"].pk}">' not in user_page
    # The POST is refused with a message, not applied.
    client.post(
        reverse("access:group_members", kwargs={"pk": declarations["Service admins"].pk}),
        {"action": "add", "user": alice.pk},
    )
    assert not alice.groups.filter(name="Service admins").exists()


def test_group_and_user_payloads_carry_the_directory_facts(declarations):
    identity, _ = directory.sign_in("entra", "oid-1", ["Service.Admin"], email="a@example.com")
    group = services.group_payload(declarations["Service admins"])
    assert group["directory_role"] == "Service.Admin" and group["grants_staff"]
    user = services.user_payload(identity.user)
    assert user["directory"] == [
        {
            "provider": "entra",
            "subject": "oid-1",
            "email": "a@example.com",
            "last_seen": identity.last_seen_at.isoformat(),
            "roles": ["Service.Admin"],
        }
    ]
    assert user["groups"][0]["source"] == "directory:entra"


# --- Findings -----------------------------------------------------------------------


def test_a_local_change_to_a_directory_group_is_a_finding(declarations, alice, settings):
    assert finding("directory_local_changes").severity == "ok"
    settings.SMALLSTACK_DIRECTORY_LOCAL_OVERRIDE = True
    services.set_membership(alice, declarations["Event planners"], True, actor=None, source="cli")
    f = finding("directory_local_changes")
    assert f.severity == "warning" and f.count == 1 and "alice added to Event planners" in f.rows[0]["label"]
    # The sync's own changes don't count.
    directory.sync_roles(alice, [], "entra")
    assert finding("directory_local_changes").count == 1


def test_superuser_from_a_directory_source_is_danger(declarations, alice):
    assert finding("directory_superuser").severity == "ok"
    from apps.access.context import acting_as

    with acting_as(None, "directory:entra"):
        alice.is_superuser = True
        alice.save()
    f = finding("directory_superuser")
    assert f.severity == "danger" and f.rows[0]["label"] == "alice"


def test_unknown_roles_and_undeclared_groups_are_reported(declarations):
    undeclared = finding("directory_undeclared_groups")
    assert undeclared.severity == "info" and [r["label"] for r in undeclared.rows] == ["Local readers"]
    assert finding("directory_unknown_roles").severity == "ok"
    directory.sign_in("entra", "oid-1", ["Service.Admin", "Usage.Viewer"])
    directory.sign_in("entra", "oid-2", ["Usage.Viewer"])
    f = finding("directory_unknown_roles")
    assert f.severity == "warning" and f.rows == [
        {"label": "Usage.Viewer", "href": reverse("access:groups"), "meta": "sent for 2 accounts"}
    ]


def test_undeclared_groups_is_quiet_when_no_group_is_directory_managed(monkeypatch):
    monkeypatch.setattr(registry, "_groups", {})
    monkeypatch.setattr(registry, "_role_overlays", {})
    ManagedGroup.objects.update(directory_role=None)
    assert finding("directory_undeclared_groups").severity == "ok"


def test_an_account_the_directory_stopped_vouching_for_with_a_live_token(declarations, settings):
    identity, _ = directory.sign_in("entra", "oid-1", ["Service.Admin"], email="a@example.com")
    APIToken.create_token(user=identity.user, name="laptop")
    assert finding("directory_unseen_with_tokens").severity == "ok"
    DirectoryIdentity.objects.filter(pk=identity.pk).update(last_seen_at=timezone.now() - timedelta(days=91))
    f = finding("directory_unseen_with_tokens")
    assert f.severity == "warning" and f.count == 1 and "entra last saw them" in f.rows[0]["meta"]
    identity.user.is_active = False
    identity.user.save()  # revokes the token
    assert finding("directory_unseen_with_tokens").severity == "ok"


# --- The manifest ---------------------------------------------------------------------


def test_the_entra_manifest_is_stable_across_runs(declarations, settings):
    settings.BRAND_NAME = "Service"
    data = directory.manifest("entra")
    roles = {r["value"]: r for r in data["appRoles"]}
    assert set(roles) == {"Service.Admin", "Events.Planner"}
    admin = roles["Service.Admin"]
    assert admin["displayName"] == "Service admins" and admin["allowedMemberTypes"] == ["User"] and admin["isEnabled"]
    assert admin["id"] == str(uuid.uuid5(directory.MANIFEST_NAMESPACE, "Service.Admin"))
    assert directory.manifest("entra")["appRoles"] == data["appRoles"]
    groups = {g["role"]: g for g in data["groups"]}
    assert groups["Events.Planner"]["displayName"] == "APP - Service - Event planners"
    assert groups["Events.Planner"]["roleId"] == roles["Events.Planner"]["id"]
    settings.SMALLSTACK_DIRECTORY_GROUP_PREFIX = "SVC-"
    assert directory.manifest("generic")["roles"][0]["directory_group"].startswith("SVC-")
    with pytest.raises(LookupError, match="Known: entra, generic"):
        directory.manifest("ldap")


def test_the_manifest_command(declarations):
    out = StringIO()
    call_command("access", "directory-manifest", stdout=out)
    text = out.getvalue()
    assert "Service.Admin" in text and "Event planners" in text and "yes" in text
    out = StringIO()
    call_command("access", "directory-manifest", "--provider", "entra", "--json", stdout=out)
    assert {r["value"] for r in json.loads(out.getvalue())["appRoles"]} == {"Service.Admin", "Events.Planner"}
    with pytest.raises(CommandError, match="No manifest format"):
        call_command("access", "directory-manifest", "--provider", "ldap", stdout=StringIO())


def test_the_manifest_command_with_nothing_declared(monkeypatch):
    monkeypatch.setattr(registry, "_groups", {})
    monkeypatch.setattr(registry, "_role_overlays", {})
    out = StringIO()
    call_command("access", "directory-manifest", stdout=out)
    assert "No group declares a directory_role" in out.getvalue()


def test_shipped_groups_stay_local_by_default():
    assert not ManagedGroup.objects.filter(group__name="Access reviewer", directory_role__isnull=False).exists()
    perm = Permission.objects.get(content_type__app_label="accounts", codename="view_user")
    assert perm in Group.objects.get(name="Access reviewer").permissions.all()


# --- Round-2 fixes (Test Lab evaluation 45) ----------------------------------------


def test_django_admin_user_form_refuses_a_directory_group(declarations, client, root, alice):
    """T2-1: the admin user form writes ``user.groups`` itself, so it must
    refuse a directory-managed group as ``set_membership`` does."""
    planners = declarations["Event planners"]
    local = declarations["Local readers"]
    client.force_login(root)
    url = reverse("admin:accounts_user_change", args=[alice.pk])
    form = {
        "username": alice.username,
        "email": alice.email,
        "is_active": "on",
        "date_joined_0": "2026-01-01",
        "date_joined_1": "00:00:00",
        "initial-date_joined_0": "2026-01-01",
        "initial-date_joined_1": "00:00:00",
    }
    response = client.post(url, {**form, "groups": [planners.pk]})
    assert response.status_code == 200  # the form comes back with the error
    assert "comes from" in response.content.decode()
    assert not alice.groups.filter(pk=planners.pk).exists()
    # A local group still saves through the same form.
    response = client.post(url, {**form, "groups": [local.pk]})
    assert response.status_code == 302
    assert alice.groups.filter(pk=local.pk).exists()


def test_the_refusal_names_each_provider_once(declarations, root):
    """T2-2: one word per provider, however many identities it has signed in."""
    for n in range(3):
        directory.sign_in("proxy", f"subject-{n}", ["Events.Planner"], email=f"u{n}@x.test")
    assert directory.providers_seen() == ["proxy"]


def test_a_directory_sign_in_stamps_last_login(declarations):
    """T2-5: an account that only ever signs in through the directory isn't
    'never signed in', and a proxy calling sign_in per request writes at most
    every LAST_LOGIN_EVERY."""
    identity, _ = directory.sign_in("proxy", "sub-t25", ["Service.Admin"], email="t25@x.test")
    user = User.objects.get(pk=identity.user_id)
    first = user.last_login
    assert first is not None
    directory.sign_in("proxy", "sub-t25", ["Service.Admin"])
    user.refresh_from_db()
    assert user.last_login == first  # throttled
    User.objects.filter(pk=user.pk).update(last_login=timezone.now() - timedelta(days=200))
    directory.sign_in("proxy", "sub-t25", ["Service.Admin"])
    user.refresh_from_db()
    assert timezone.now() - user.last_login < timedelta(minutes=1)
    assert user.username not in {r["label"] for r in finding("dormant_privileged").rows}
