"""The group writes over REST and from the shell: the same services as the
group page (create, rename, permissions, delete, a direct permission off an
account), the same refusals, recorded from ``rest`` / ``cli``."""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import CommandError, call_command

from apps.access import registry
from apps.access.models import AccessEvent
from apps.access.registry import register_group, sync_groups
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
BASE = "/smallstack/api/access/"


def perm(name: str) -> Permission:
    app, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


def bearer(user, level="auth"):
    _token, raw = APIToken.create_token(user=user, name=f"t-{level}", access_level=level)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def run(*args):
    out = StringIO()
    call_command("access", *args, stdout=out)
    return out.getvalue()


@pytest.fixture
def group_manager(db):
    user = User.objects.create_user("gm", password="p", is_staff=True)
    user.user_permissions.add(
        perm("auth.add_group"),
        perm("auth.change_group"),
        perm("auth.delete_group"),
        perm("accounts.view_user"),
        perm("accounts.change_user"),
    )
    return User.objects.get(pk=user.pk)


# --- REST ---------------------------------------------------------------------------


def test_rest_creates_renames_grants_and_deletes_recorded_from_rest(client, group_manager, alice):
    h = bearer(group_manager)
    resp = client.post(BASE + "groups/", json.dumps({"name": "Helpdesk"}), content_type="application/json", **h)
    assert resp.status_code == 201 and resp.json()["name"] == "Helpdesk"
    group = Group.objects.get(name="Helpdesk")
    assert AccessEvent.objects.get(kind="group_created", group=group).source == "rest"
    # Rename.
    resp = client.patch(
        BASE + "groups/Helpdesk/", json.dumps({"name": "Help desk"}), content_type="application/json", **h
    )
    assert resp.status_code == 200 and resp.json()["name"] == "Help desk" and resp.json()["changed"] is True
    assert AccessEvent.objects.filter(kind="group_renamed", group=group, actor=group_manager).exists()
    # A permission the caller holds goes on; one they don't is refused; an unknown one is 404.
    url = BASE + "groups/Help desk/permissions/"
    assert client.put(url + "accounts.view_user/", **h).json() == {
        "group": "Help desk",
        "permission": "accounts.view_user",
        "held": True,
        "changed": True,
    }
    assert client.put(url + "accounts.view_user/", **h).json()["changed"] is False
    refused = client.put(url + "accounts.delete_user/", **h)
    assert refused.status_code == 403 and "hold" in refused.json()["errors"]["__all__"][0]
    assert client.put(url + "nope.nothing/", **h).status_code == 404
    assert client.delete(url + "accounts.view_user/", **h).json()["changed"] is True
    assert AccessEvent.objects.filter(kind="group_permission_removed", group=group, source="rest").exists()
    # Delete: the member keeps their account.
    alice.groups.add(group)
    resp = client.delete(BASE + "groups/Help desk/", **h)
    assert resp.json() == {"group": "Help desk", "deleted": True}
    assert not Group.objects.filter(pk=group.pk).exists() and User.objects.filter(pk=alice.pk).exists()
    assert client.get(BASE + "groups/", **h).status_code == 200  # the GET on the same path still reads


def test_rest_refusals_and_bad_input(client, group_manager, staffer, root, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    h = bearer(group_manager)
    assert (
        client.post(BASE + "groups/", json.dumps({"name": " "}), content_type="application/json", **h).status_code
        == 400
    )
    Group.objects.create(name="Taken")
    resp = client.post(BASE + "groups/", json.dumps({"name": "Taken"}), content_type="application/json", **h)
    assert resp.status_code == 400 and "already exists" in resp.json()["errors"]["__all__"][0]
    # A reader's token: the auth.*_group permission is what's missing.
    refused = client.post(
        BASE + "groups/", json.dumps({"name": "X"}), content_type="application/json", **bearer(staffer)
    )
    assert refused.status_code == 403 and "auth.add_group" in refused.json()["errors"]["__all__"][0]
    # A login-level token can't write, whoever holds it.
    refused = client.delete(BASE + "groups/Taken/", **bearer(group_manager, ""))
    assert refused.status_code == 403 and "Auth-level token" in refused.json()["errors"]["__all__"][0]
    assert Group.objects.filter(name="Taken").exists()
    # A group declared in code: no rename or delete, even for a superuser.
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests")
    sync_groups()
    resp = client.delete(BASE + "groups/Declared/", **bearer(root))
    assert resp.status_code == 403 and "declared in code" in resp.json()["errors"]["__all__"][0]
    assert client.get(BASE + "groups/Nope/", **h).status_code == 404


def test_rest_takes_a_direct_permission_off(client, group_manager, alice, root):
    alice.user_permissions.add(perm("accounts.view_user"))
    h = bearer(group_manager)
    resp = client.delete(BASE + "users/alice/permissions/accounts.view_user/", **h)
    assert resp.json() == {"username": "alice", "permission": "accounts.view_user", "held": False, "changed": True}
    assert not alice.user_permissions.exists()
    assert AccessEvent.objects.filter(kind="permission_removed", subject=alice, source="rest").exists()
    assert client.delete(BASE + "users/alice/permissions/accounts.view_user/", **h).json()["changed"] is False
    assert client.put(BASE + "users/alice/permissions/accounts.view_user/", **h).status_code == 405  # no add
    root.user_permissions.add(perm("accounts.view_user"))
    assert client.delete(BASE + "users/root/permissions/accounts.view_user/", **h).status_code == 403


def test_the_group_writes_are_in_the_openapi_schema(client, root):
    client.force_login(root)
    paths = client.get("/api/schema/openapi.json").json()["paths"]
    assert set(paths["/smallstack/api/access/groups/"]) >= {"get", "post"}
    assert set(paths["/smallstack/api/access/groups/{group}/"]) >= {"get", "patch", "delete"}
    assert set(paths["/smallstack/api/access/groups/{group}/permissions/{perm}/"]) == {"put", "delete"}
    assert set(paths["/smallstack/api/access/users/{user}/permissions/{perm}/"]) == {"delete"}


# --- CLI ------------------------------------------------------------------------------


def test_the_shell_manages_groups(alice, root, group_manager):
    assert "Group Helpdesk created" in run("group", "new", "Helpdesk")
    group = Group.objects.get(name="Helpdesk")
    created = AccessEvent.objects.get(kind="group_created", group=group)
    assert created.actor is None and created.source == "cli"
    assert "renamed to Help desk" in run("group", "rename", "Helpdesk", "Help desk", "--user", "gm")
    assert AccessEvent.objects.get(kind="group_renamed", group=group).actor == group_manager
    assert "accounts.view_user added to Help desk" in run("group", "grant", "Help desk", "accounts.view_user")
    assert "nothing changed" in run("group", "grant", "Help desk", "accounts.view_user")
    # With --user the subset rule applies; without it, a local command grants anything.
    with pytest.raises(CommandError, match="hold"):
        run("group", "grant", "Help desk", "accounts.delete_user", "--user", "gm")
    assert "accounts.delete_user added" in run(
        "group", "grant", "Help desk", "accounts.delete_user", "--reason", "ticket 12"
    )
    assert (
        AccessEvent.objects.get(kind="group_permission_added", permission="accounts.delete_user").source
        == "cli: ticket 12"
    )
    assert "removed from Help desk" in run("group", "revoke", "Help desk", "accounts.delete_user")
    with pytest.raises(CommandError, match="No permission"):
        run("group", "grant", "Help desk", "nope.nothing")
    alice.user_permissions.add(perm("accounts.view_user"))
    assert "removed from alice" in run("perm", "rm", "alice", "accounts.view_user", "--user", "gm")
    assert not alice.user_permissions.exists()
    alice.groups.add(group)
    assert "Group Help desk deleted" in run("group", "rm", "Help desk")
    assert not Group.objects.filter(pk=group.pk).exists() and User.objects.filter(pk=alice.pk).exists()


def test_the_shell_keeps_the_groups_rules(root, staffer, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    with pytest.raises(CommandError, match="auth.add_group"):
        run("group", "new", "X", "--user", "staffer")
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests")
    sync_groups()
    with pytest.raises(CommandError, match="declared in code"):
        run("group", "rm", "Declared")
    with pytest.raises(CommandError, match="declared in code"):
        run("group", "rename", "Declared", "Other", "--user", "root")
    assert Group.objects.filter(name="Declared").exists()
    assert "accounts.change_user added to Declared" in run("group", "grant", "Declared", "accounts.change_user")
    with pytest.raises(CommandError, match="already exists"):
        run("group", "new", "Declared")
    with pytest.raises(CommandError, match="No group"):
        run("group", "rm", "Nope")
