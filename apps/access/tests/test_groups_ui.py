"""Groups are managed on the Access pages, not in Django admin: create,
rename, what a group grants, delete, and taking a direct permission off an
account. Every write goes through the services (recorded, the same refusals
on every surface); the Permissions card swaps in place over htmx."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse

from apps.access import registry, services
from apps.access.models import AccessEvent
from apps.access.registry import register_group, sync_groups

pytestmark = pytest.mark.django_db

User = get_user_model()
HX = {"HTTP_HX_REQUEST": "true"}


def perm(name: str) -> Permission:
    app, codename = name.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def group_manager(db):
    """Staff holding the auth group permissions and accounts.view_user (to
    read the pages), plus accounts.change_user (to change what accounts hold)."""
    user = User.objects.create_user("gm", password="p", is_staff=True)
    user.user_permissions.add(
        perm("auth.add_group"),
        perm("auth.change_group"),
        perm("auth.delete_group"),
        perm("accounts.view_user"),
        perm("accounts.change_user"),
    )
    return User.objects.get(pk=user.pk)


def events(kind: str, **filters):
    return AccessEvent.objects.filter(kind=kind, **filters)


# --- The services ------------------------------------------------------------------


def test_create_rename_permissions_and_delete_are_recorded(group_manager):
    group = services.create_group("Helpdesk", actor=group_manager, source="web:/x/")
    created = events("group_created", group=group).get()
    assert created.actor == group_manager and created.source == "web:/x/"
    assert services.rename_group(group, "Help desk", actor=group_manager, source="web:/x/")
    assert events("group_renamed").get().detail == {"from": "Helpdesk", "to": "Help desk"}
    assert not services.rename_group(group, "Help desk", actor=group_manager, source="web:/x/")
    assert services.set_group_permission(group, "accounts.view_user", True, actor=group_manager, source="web:/x/")
    assert events("group_permission_added", group=group, permission="accounts.view_user").get().actor == group_manager
    assert not services.set_group_permission(group, "accounts.view_user", True, actor=group_manager, source="web:/x/")
    assert services.set_group_permission(group, "accounts.view_user", False, actor=group_manager, source="web:/x/")
    assert events("group_permission_removed", group=group, permission="accounts.view_user").exists()
    services.delete_group(group, actor=group_manager, source="web:/x/")
    assert not Group.objects.filter(name="Help desk").exists()
    assert events("group_deleted", group_label="Help desk").exists()


def test_the_refusals(group_manager, root, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    plain = User.objects.create_user("plain", password="p", is_staff=True)
    assert "lacks auth.add_group" in services.group_refusal(plain, action="create")
    with pytest.raises(services.GroupRefused):
        services.create_group("X", actor=plain, source="web:/x/")
    with pytest.raises(services.GroupRefused, match="needs a name"):
        services.create_group("  ", actor=group_manager, source="web:/x/")
    Group.objects.create(name="Taken")
    with pytest.raises(services.GroupRefused, match="already exists"):
        services.create_group("Taken", actor=group_manager, source="web:/x/")
    # Nobody hands a group a permission they don't hold; a superuser holds all.
    group = Group.objects.create(name="Ops")
    with pytest.raises(services.GroupRefused, match="don't hold"):
        services.set_group_permission(group, "accounts.delete_user", True, actor=group_manager, source="web:/x/")
    assert services.set_group_permission(group, "accounts.delete_user", True, actor=root, source="web:/x/")
    with pytest.raises(services.GroupRefused, match="No permission"):
        services.set_group_permission(group, "nope.nothing", True, actor=root, source="web:/x/")
    # A group declared in code can change its permissions (drift), not its name or existence.
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests")
    sync_groups()
    declared = Group.objects.get(name="Declared")
    assert "declared in code" in services.group_refusal(root, declared, action="rename")
    assert "declared in code" in services.group_refusal(root, declared, action="delete")
    assert services.group_refusal(root, declared, action="permissions") == ""
    # A directory-managed group: nothing changes here.
    register_group("Dir", permissions=["accounts.view_user"], app_label="tests", directory_role="Dir.Role")
    sync_groups()
    directory = Group.objects.get(name="Dir")
    for action in ("rename", "permissions", "delete"):
        assert "directory-managed" in services.group_refusal(root, directory, action=action)


def test_direct_permissions_come_off_but_never_on(group_manager, root, alice):
    alice.user_permissions.add(perm("accounts.view_user"))
    assert services.remove_direct_permission(alice, "accounts.view_user", actor=group_manager, source="web:/x/")
    assert events("permission_removed", subject=alice, permission="accounts.view_user").get().actor == group_manager
    assert not services.remove_direct_permission(alice, "accounts.view_user", actor=group_manager, source="web:/x/")
    assert "Only a superuser" in services.direct_permission_refusal(group_manager, root)
    assert not hasattr(services, "add_direct_permission")


# --- The pages ------------------------------------------------------------------------


def test_the_groups_page_creates_without_django_admin(client, group_manager, staffer):
    client.force_login(group_manager)
    page = client.get(reverse("access:groups")).content.decode()
    # A New group button opens a modal holding the form; no inline name field in the header.
    assert 'data-dialog-open="new-group"' in page and '<dialog id="new-group"' in page
    assert 'id="new-group-name"' in page and "Create group" in page and "/admin/auth/group/" not in page
    resp = client.post(reverse("access:group_create"), {"name": "Helpdesk"})
    group = Group.objects.get(name="Helpdesk")
    assert resp["Location"] == reverse("access:group_detail", kwargs={"pk": group.pk})
    assert events("group_created", group=group).get().source == "web:/smallstack/access/groups/new/"
    # A reader sees no button or modal and can't post one.
    client.force_login(staffer)
    page = client.get(reverse("access:groups")).content.decode()
    assert "New group" not in page and "<dialog" not in page
    resp = client.post(reverse("access:group_create"), {"name": "Nope"}, follow=True)
    assert not Group.objects.filter(name="Nope").exists() and "lacks auth.add_group" in resp.content.decode()


def test_the_new_group_modal_over_htmx(client, group_manager):
    """A refusal comes back as the modal's form with the reason and the name
    kept (no page swap, no message elsewhere); success redirects the browser."""
    client.force_login(group_manager)
    url = reverse("access:group_create")
    Group.objects.create(name="Taken")
    resp = client.post(url, {"name": "Taken"}, **HX)
    html = resp.content.decode()
    assert resp.status_code == 200 and html.lstrip().startswith("<form") and "<html" not in html
    assert 'id="new-group-form"' in html and 'value="Taken"' in html and "already exists" in html
    assert 'aria-invalid="true"' in html and Group.objects.filter(name="Taken").count() == 1
    assert "needs a name" in client.post(url, {"name": "  "}, **HX).content.decode()
    resp = client.post(url, {"name": "Helpdesk"}, **HX)
    group = Group.objects.get(name="Helpdesk")
    assert resp.status_code == 204 and resp["HX-Redirect"] == reverse("access:group_detail", kwargs={"pk": group.pk})


def test_the_group_page_edits_permissions_over_htmx(client, group_manager, staffer):
    group = Group.objects.create(name="Helpdesk")
    client.force_login(group_manager)
    url = reverse("access:group_permissions", kwargs={"pk": group.pk})
    page = client.get(reverse("access:group_detail", kwargs={"pk": group.pk})).content.decode()
    assert "/admin/auth/group/" not in page and 'id="group-permissions"' in page and "Add permissions" in page
    # The picker offers what the viewer holds, not what they don't.
    assert 'value="accounts.view_user"' in page and 'value="accounts.delete_user"' not in page
    resp = client.post(url, {"action": "add", "perm": "accounts.view_user"}, **HX)
    html = resp.content.decode()
    assert resp.status_code == 200 and html.lstrip().startswith("<div") and "<html" not in html
    assert 'id="group-permissions"' in html and "accounts.view_user" in html and "hx-swap-oob" in html
    assert "added to Helpdesk" in html
    assert group.permissions.filter(codename="view_user").exists()
    resp = client.post(url, {"action": "remove", "perm": "accounts.view_user"}, **HX)
    assert "removed from Helpdesk" in resp.content.decode() and not group.permissions.exists()
    # A plain post goes back to the page; a refusal is a message, not a 500.
    resp = client.post(url, {"action": "add", "perm": "accounts.delete_user"}, follow=True)
    assert "hold it" in resp.content.decode() and not group.permissions.exists()  # the refusal, HTML-escaped
    assert client.post(url, {"action": "wat", "perm": "x"}).status_code == 400
    # A reader sees the card without controls.
    client.force_login(staffer)
    page = client.get(reverse("access:group_detail", kwargs={"pk": group.pk})).content.decode()
    assert 'id="group-permissions"' in page and "Add permissions" not in page


def test_the_group_page_renames_and_deletes(client, group_manager, alice):
    group = Group.objects.create(name="Helpdesk")
    alice.groups.add(group)
    client.force_login(group_manager)
    url = reverse("access:group_settings", kwargs={"pk": group.pk})
    page = client.get(reverse("access:group_detail", kwargs={"pk": group.pk})).content.decode()
    assert "Rename" in page and "Delete group" in page
    client.post(url, {"action": "rename", "name": "Help desk"})
    group.refresh_from_db()
    assert group.name == "Help desk" and events("group_renamed").exists()
    resp = client.post(url, {"action": "delete"})
    assert resp["Location"] == reverse("access:groups")
    assert not Group.objects.filter(pk=group.pk).exists() and events("group_deleted").exists()
    assert User.objects.filter(pk=alice.pk).exists()  # the member keeps their account


def test_a_declared_group_page_offers_no_rename_or_delete(client, root, monkeypatch):
    monkeypatch.setattr(registry, "_groups", dict(registry._groups))
    register_group("Declared", permissions=["accounts.view_user"], app_label="tests")
    sync_groups()
    group = Group.objects.get(name="Declared")
    client.force_login(root)
    page = client.get(reverse("access:group_detail", kwargs={"pk": group.pk})).content.decode()
    assert "Delete group" not in page and 'name="action" value="rename"' not in page
    assert "Add permissions" in page  # its permissions can still change (as drift)
    resp = client.post(reverse("access:group_settings", kwargs={"pk": group.pk}), {"action": "delete"}, follow=True)
    assert Group.objects.filter(pk=group.pk).exists() and "declared in code" in resp.content.decode()


def test_the_user_page_removes_a_direct_permission(client, group_manager, alice, root):
    alice.user_permissions.add(perm("accounts.view_user"))
    client.force_login(group_manager)
    page = client.get(reverse("access:user_detail", kwargs={"pk": alice.pk})).content.decode()
    assert "Remove direct" in page and "/admin/accounts/user/" not in page
    resp = client.post(
        reverse("access:user_permissions", kwargs={"pk": alice.pk}), {"action": "remove", "perm": "accounts.view_user"}
    )
    assert resp.status_code == 302 and not alice.user_permissions.exists()
    # A superuser's direct permissions are a superuser's to change.
    root.user_permissions.add(perm("accounts.view_user"))
    page = client.get(reverse("access:user_detail", kwargs={"pk": root.pk})).content.decode()
    assert "Remove direct" not in page
    client.post(
        reverse("access:user_permissions", kwargs={"pk": root.pk}), {"action": "remove", "perm": "accounts.view_user"}
    )
    assert root.user_permissions.exists()
