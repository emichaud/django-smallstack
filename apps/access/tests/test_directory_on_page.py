"""A group made on the Access pages can be directory-managed exactly as one
declared with ``directory_role=``: mark it (page, REST, CLI), members come from
the directory at sign-in and can't be changed here, current members keep it
until their next sign-in, and unmarking makes it local again. Plus the
multi-select pickers that add and remove several at once."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.access import directory, registry, services
from apps.access.models import AccessEvent, ManagedGroup
from apps.access.registry import register_group, sync_groups
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
HX = {"HTTP_HX_REQUEST": "true"}


def perm(name: str) -> Permission:
    app, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def gm(db):
    """A group manager: the auth group permissions, plus reading and changing accounts."""
    user = User.objects.create_user("gm", password="p", is_staff=True)
    user.user_permissions.add(
        *[
            perm(p)
            for p in (
                "auth.add_group",
                "auth.change_group",
                "auth.delete_group",
                "accounts.view_user",
                "accounts.change_user",
            )
        ]
    )
    return User.objects.get(pk=user.pk)


@pytest.fixture
def editors(db):
    group = Group.objects.create(name="Blog editors")
    group.permissions.add(perm("accounts.view_user"))
    return group


def role_of(group: Group) -> str:
    managed = ManagedGroup.objects.filter(group=group).first()
    return (managed.directory_role or "") if managed else ""


# --- The service ---------------------------------------------------------------------


def test_marking_unmarking_and_the_record(gm, editors, alice):
    alice.groups.add(editors)
    assert services.suggested_role("Blog editors") == "Blog.Editors"
    assert services.set_directory_role(editors, "Blog.Editors", actor=gm, source="web:/x/")
    managed = ManagedGroup.objects.get(group=editors)
    assert (managed.source, managed.directory_role, managed.grants_staff) == ("page", "Blog.Editors", False)
    assert managed.drift() == {"added": [], "missing": []}  # a page group has no declaration to drift from
    event = AccessEvent.objects.get(kind="directory_role_set")
    assert event.actor == gm and event.detail == {"from": "", "to": "Blog.Editors", "staff": False, "members": 1}
    # Members stay until their next directory sign-in; local changes are refused now.
    assert alice.groups.filter(pk=editors.pk).exists()
    with pytest.raises(services.MembershipRefused, match="comes from"):
        services.set_membership(alice, editors, False, actor=gm, source="web:/x/")
    # Its name and permissions are still the page's to change.
    assert services.rename_group(editors, "Blog editors team", actor=gm, source="web:/x/")
    assert services.set_group_permission(editors, "accounts.change_user", True, actor=gm, source="web:/x/")
    # Staff only, then unmark: local again, members kept, recorded.
    assert services.set_directory_role(editors, "Blog.Editors", staff=True, actor=gm, source="web:/x/")
    assert not services.set_directory_role(editors, "Blog.Editors", staff=True, actor=gm, source="web:/x/")
    assert services.set_directory_role(editors, "", actor=gm, source="web:/x/")
    assert not ManagedGroup.objects.filter(group=editors).exists() and alice.groups.filter(pk=editors.pk).exists()
    assert services.set_membership(alice, editors, False, actor=gm, source="web:/x/")
    assert AccessEvent.objects.filter(kind="directory_role_set").count() == 3


def test_the_refusals(gm, editors, staffer, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    with pytest.raises(services.GroupRefused, match="auth.change_group"):
        services.set_directory_role(editors, "Blog.Editors", actor=staffer, source="web:/x/")
    with pytest.raises(services.GroupRefused, match="no spaces") as bad:
        services.set_directory_role(editors, "Blog editors", actor=gm, source="web:/x/")
    assert bad.value.status == 400
    other = Group.objects.create(name="Other")
    services.set_directory_role(other, "Blog.Editors", actor=gm, source="web:/x/")
    with pytest.raises(services.GroupRefused, match="already belongs to group 'Other'"):
        services.set_directory_role(editors, "Blog.Editors", actor=gm, source="web:/x/")
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests", directory_role="Code.Role")
    sync_groups()
    with pytest.raises(services.GroupRefused, match="declared in code"):
        services.set_directory_role(Group.objects.get(name="Declared"), "X.Y", actor=gm, source="web:/x/")
    with pytest.raises(services.GroupRefused, match="already belongs to group 'Declared'"):
        services.set_directory_role(editors, "Code.Role", actor=gm, source="web:/x/")


def test_sam_signs_up_with_the_role_then_entra_removes_it(gm, editors):
    """The scenario: a page group marked with a role; a new sign-in carrying the
    role joins it and gets its permissions; the role gone, the next sign-in
    removes him; an absent claim changes nothing."""
    services.set_directory_role(editors, "Blog.Editors", actor=gm, source="web:/x/")
    identity, result = directory.sign_in("entra", "oid-sam", ["Blog.Editors"], email="sam@example.com", name="Sam")
    sam = User.objects.get(pk=identity.user.pk)
    assert sam.groups.filter(pk=editors.pk).exists() and sam.has_perm("accounts.view_user")
    assert AccessEvent.objects.get(kind="group_added", subject=sam).source == "directory:entra"
    directory.sign_in("entra", "oid-sam", None, email="sam@example.com")  # the claim missing: no change
    assert sam.groups.filter(pk=editors.pk).exists()
    directory.sign_in("entra", "oid-sam", [], email="sam@example.com")  # the role taken away
    sam = User.objects.get(pk=sam.pk)
    assert not sam.groups.filter(pk=editors.pk).exists() and not sam.has_perm("accounts.view_user")


def test_the_manifest_and_payload_include_page_groups(gm, editors):
    services.set_directory_role(editors, "Blog.Editors", staff=True, actor=gm, source="web:/x/")
    roles = {r.role: r for r in directory.manifest_roles()}
    assert roles["Blog.Editors"].group == "Blog editors" and roles["Blog.Editors"].staff
    payload = services.group_payload(editors)
    assert (
        payload["directory_managed"] and not payload["declared_in_code"] and payload["directory_role"] == "Blog.Editors"
    )


# --- The page -------------------------------------------------------------------------


def test_the_group_page_marks_and_unmarks(client, gm, editors, alice):
    alice.groups.add(editors)
    client.force_login(gm)
    url = reverse("access:group_detail", kwargs={"pk": editors.pk})
    page = client.get(url).content.decode()
    assert "Make directory-managed" in page and 'value="Blog.Editors"' in page and "Add people" in page
    client.post(reverse("access:group_directory", kwargs={"pk": editors.pk}), {"role": "Blog.Editors", "staff": "on"})
    assert role_of(editors) == "Blog.Editors" and ManagedGroup.objects.get(group=editors).grants_staff
    page = client.get(url).content.decode()
    assert "directory-managed" in page and "Add people" not in page and "Make local" in page
    assert "alice@example.com" in page  # the list for the directory administrator
    # A post to add is refused, not applied.
    bob = User.objects.create_user("bob", password="p")
    client.post(reverse("access:group_members", kwargs={"pk": editors.pk}), {"action": "add", "user": bob.pk})
    assert not bob.groups.exists()
    resp = client.post(reverse("access:group_directory", kwargs={"pk": editors.pk}), {"action": "unmark"}, follow=True)
    assert role_of(editors) == "" and "is local again" in resp.content.decode()
    resp = client.post(reverse("access:group_directory", kwargs={"pk": editors.pk}), {"role": "bad role"}, follow=True)
    assert role_of(editors) == "" and "no spaces" in resp.content.decode()


def test_a_declared_groups_role_is_read_only_on_the_page(client, gm, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests", directory_role="Code.Role")
    sync_groups()
    group = Group.objects.get(name="Declared")
    client.force_login(gm)
    page = client.get(reverse("access:group_detail", kwargs={"pk": group.pk})).content.decode()
    assert "Code.Role" in page and "change the role there" in page and "Make local" not in page


def test_the_pickers_add_and_remove_several_at_once(client, gm, editors, alice):
    bob = User.objects.create_user("bob", password="p")
    client.force_login(gm)
    members = reverse("access:group_members", kwargs={"pk": editors.pk})
    resp = client.post(members, {"action": "add", "user": [alice.pk, bob.pk]}, **HX)
    html = resp.content.decode()
    assert 'id="group-members"' in html and "<html" not in html and "alice, bob added to Blog editors" in html
    assert set(editors.user_set.values_list("username", flat=True)) == {"alice", "bob"}
    client.post(members, {"action": "remove", "user": [alice.pk, bob.pk]}, **HX)
    assert not editors.user_set.exists()
    assert client.post(members, {"action": "add", "user": ["abc"]}).status_code == 404
    perms = reverse("access:group_permissions", kwargs={"pk": editors.pk})
    client.post(perms, {"action": "add", "perm": ["accounts.change_user", "auth.change_group"]}, **HX)
    assert {p.codename for p in editors.permissions.all()} == {"view_user", "change_user", "change_group"}
    # One refused (gm doesn't hold it), the others still applied, the reason said once.
    html = client.post(
        perms, {"action": "add", "perm": ["accounts.delete_user", "auth.add_group"]}, **HX
    ).content.decode()
    assert editors.permissions.filter(codename="add_group").exists() and "hold it" in html
    client.post(perms, {"action": "remove", "perm": ["accounts.change_user", "auth.change_group"]}, **HX)
    assert {p.codename for p in editors.permissions.all()} == {"view_user", "add_group"}


def test_the_user_page_adds_to_several_groups(client, gm, alice, editors):
    ops = Group.objects.create(name="Ops")
    client.force_login(gm)
    page = client.get(reverse("access:user_detail", kwargs={"pk": alice.pk})).content.decode()
    assert "Add to groups" in page and f'name="group" value="{ops.pk}"' in page
    client.post(
        reverse("access:user_groups", kwargs={"pk": alice.pk}), {"action": "add", "group": [ops.pk, editors.pk]}
    )
    assert set(alice.groups.values_list("name", flat=True)) == {"Ops", "Blog editors"}
    services.set_directory_role(editors, "Blog.Editors", actor=gm, source="web:/x/")
    page = client.get(reverse("access:user_detail", kwargs={"pk": alice.pk})).content.decode()
    assert f'name="group" value="{editors.pk}"' not in page  # a managed group isn't offered


# --- REST and CLI ------------------------------------------------------------------------


def test_rest_marks_and_unmarks(client, gm, editors):
    _t, raw = APIToken.create_token(user=gm, name="t", access_level="auth")
    h = {"HTTP_AUTHORIZATION": f"Bearer {raw}"}
    url = "/smallstack/api/access/groups/Blog editors/"
    body = json.dumps({"directory_role": "Blog.Editors", "staff": True})
    data = client.patch(url, body, content_type="application/json", **h).json()
    assert data["directory_managed"] and data["directory_role"] == "Blog.Editors" and data["grants_staff"]
    assert AccessEvent.objects.get(kind="directory_role_set").source == "rest"
    bad = client.patch(url, json.dumps({"directory_role": "has space"}), content_type="application/json", **h)
    assert bad.status_code == 400
    assert client.patch(url, json.dumps({"staff": "yes"}), content_type="application/json", **h).status_code == 400
    data = client.patch(url, json.dumps({"directory_role": ""}), content_type="application/json", **h).json()
    assert not data["directory_managed"] and role_of(editors) == ""
    assert client.patch(url, json.dumps({}), content_type="application/json", **h).status_code == 400


def test_the_cli_marks_and_unmarks(gm, editors, monkeypatch):
    out = StringIO()
    call_command("access", "group", "role", "Blog editors", "Blog.Editors", "--staff", "--user", "gm", stdout=out)
    assert "directory-managed with role Blog.Editors" in out.getvalue() and role_of(editors) == "Blog.Editors"
    assert AccessEvent.objects.get(kind="directory_role_set").actor == gm
    out = StringIO()
    call_command("access", "group", "role", "Blog editors", "", stdout=out)
    assert "local again" in out.getvalue() and role_of(editors) == ""
    with pytest.raises(CommandError, match="no spaces"):
        call_command("access", "group", "role", "Blog editors", "bad role", stdout=StringIO())
