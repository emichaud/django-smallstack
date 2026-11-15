"""G3-2: Django admin follows the User Manager's rules for the account flags.

Before the fix a *User manager* (staff + ``change_user``) could untick a
superuser's ``is_active`` or ``is_staff`` in ``/admin/``, which the User
Manager and REST refuse, and nothing in admin stopped the last active
superuser being deactivated. Admin now matches the User Manager
(``can_edit_account`` + its guardrails), no stricter and no looser.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()

USER_MANAGER = ["view_user", "add_user", "change_user", "delete_user"]
OPTS = User._meta


def _fresh(user):
    return User.objects.get(pk=user.pk)


def _change_url(user) -> str:
    return reverse(f"admin:{OPTS.app_label}_{OPTS.model_name}_change", args=[user.pk])


def _delete_url(user) -> str:
    return reverse(f"admin:{OPTS.app_label}_{OPTS.model_name}_delete", args=[user.pk])


def _client(user) -> Client:
    c = Client()
    c.force_login(user)
    return c


def _admin_post(target, *, as_superuser: bool, **changes) -> dict:
    """The admin change form's POST for ``target`` with ``changes`` applied.
    A superuser's form also carries ``is_superuser``; anyone else's doesn't
    (it's read-only for them)."""
    data = {
        "username": target.username,
        "email": target.email,
        "first_name": target.first_name,
        "last_name": target.last_name,
        "is_active": target.is_active,
        "is_staff": target.is_staff,
    }
    if as_superuser:
        data["is_superuser"] = target.is_superuser
    data.update(changes)
    return {k: "on" if v is True else v for k, v in data.items() if v is not False}


@pytest.fixture
def root():
    return User.objects.create_superuser("root", "root@acme.test", "pw")


@pytest.fixture
def su2():
    return User.objects.create_superuser("su2", "su2@acme.test", "pw")


@pytest.fixture
def manager():
    user = User.objects.create_user("uma", password="pw", email="uma@acme.test", is_staff=True)
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="accounts", codename__in=USER_MANAGER)
    )
    return _fresh(user)


@pytest.fixture
def god():
    """A non-superuser holding every permission (wider than the manager)."""
    user = User.objects.create_user("god", password="pw", email="god@acme.test", is_staff=True)
    user.user_permissions.add(*Permission.objects.all())
    return _fresh(user)


# --- a User manager and a superuser ------------------------------------------


def test_g3_2_user_manager_cannot_deactivate_a_superuser_in_admin(manager, su2):
    resp = _client(manager).post(_change_url(su2), _admin_post(su2, as_superuser=False, is_active=False))
    assert resp.status_code == 403
    assert _fresh(su2).is_active


def test_g3_2_user_manager_cannot_remove_a_superusers_staff_flag_in_admin(manager, su2):
    resp = _client(manager).post(_change_url(su2), _admin_post(su2, as_superuser=False, is_staff=False))
    assert resp.status_code == 403
    assert _fresh(su2).is_staff


def test_g3_2_a_superusers_admin_page_opens_read_only_for_a_user_manager(manager, su2):
    resp = _client(manager).get(_change_url(su2))
    assert resp.status_code == 200  # view_user: they may look
    body = resp.content.decode()
    assert 'name="is_active"' not in body
    assert 'name="is_staff"' not in body


def test_g3_2_user_manager_cannot_delete_a_superuser_in_admin(manager, su2):
    c = _client(manager)
    assert c.post(_delete_url(su2), {"post": "yes"}).status_code == 403
    changelist = reverse(f"admin:{OPTS.app_label}_{OPTS.model_name}_changelist")
    c.post(changelist, {"action": "delete_selected", "_selected_action": [su2.pk], "post": "yes"})
    assert User.objects.filter(pk=su2.pk).exists()


def test_g3_2_a_wide_non_superuser_cannot_delete_a_superuser_in_admin(god, su2):
    """The User manager above is stopped by the cascade's permissions alone;
    an account holding every permission is not, and the User Manager's rule
    (a superuser's account only by a superuser) is what refuses it."""
    c = _client(god)
    assert c.post(_delete_url(su2), {"post": "yes"}).status_code == 403
    changelist = reverse(f"admin:{OPTS.app_label}_{OPTS.model_name}_changelist")
    c.post(changelist, {"action": "delete_selected", "_selected_action": [su2.pk], "post": "yes"})
    assert User.objects.filter(pk=su2.pk).exists()
    plain = User.objects.create_user("plain3", password="pw")
    c.post(_delete_url(plain), {"post": "yes"})
    assert not User.objects.filter(pk=plain.pk).exists()  # control


# --- what stays allowed (no stricter than the User Manager) -------------------


def test_g3_2_user_manager_may_still_change_a_wider_accounts_flags(manager, god):
    """The User Manager lets a User manager edit a wider account's staff and
    active flags (the subset rule covers sign-in fields only); so does admin."""
    resp = _client(manager).post(_change_url(god), _admin_post(god, as_superuser=False, is_active=False))
    assert resp.status_code == 302
    assert not _fresh(god).is_active


def test_g3_2_superuser_may_deactivate_another_superuser(root, su2):
    resp = _client(root).post(_change_url(su2), _admin_post(su2, as_superuser=True, is_active=False))
    assert resp.status_code == 302
    assert not _fresh(su2).is_active


def test_g3_2_superuser_may_demote_another_superuser(root, su2):
    resp = _client(root).post(_change_url(su2), _admin_post(su2, as_superuser=True, is_superuser=False))
    assert resp.status_code == 302
    assert not _fresh(su2).is_superuser


# --- yourself and the last active superuser -----------------------------------


@pytest.mark.parametrize("flag", ["is_active", "is_staff", "is_superuser"])
def test_g3_2_the_last_active_superuser_cannot_be_deactivated_or_demoted(root, flag):
    resp = _client(root).post(_change_url(root), _admin_post(root, as_superuser=True, **{flag: False}))
    assert resp.status_code == 200  # the form again, with the error
    fresh = _fresh(root)
    assert fresh.is_active and fresh.is_staff and fresh.is_superuser


def test_g3_2_a_user_manager_cannot_remove_their_own_staff_flag(manager):
    resp = _client(manager).post(_change_url(manager), _admin_post(manager, as_superuser=False, is_staff=False))
    assert resp.status_code == 200
    assert _fresh(manager).is_staff


def test_g3_2_nobody_deletes_their_own_account_in_admin(manager):
    assert _client(manager).post(_delete_url(manager), {"post": "yes"}).status_code == 403
    assert User.objects.filter(pk=manager.pk).exists()


def test_g3_2_bulk_delete_cannot_remove_the_last_active_superuser(root, su2):
    """root may delete su2, but not su2 and root together (no active superuser left);
    and the ``delete_queryset`` guard refuses the set as a whole."""
    from django.contrib import admin
    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory

    model_admin = admin.site._registry[User]
    request = RequestFactory().post("/")
    request.user = root
    with pytest.raises(PermissionDenied):
        model_admin.delete_queryset(request, User.objects.filter(pk__in=[su2.pk, root.pk]))
    assert User.objects.filter(pk__in=[su2.pk, root.pk]).count() == 2


# --- Explorer had the same hole (its account form) ----------------------------


def test_g3_2_explorer_cannot_deactivate_a_superuser(manager, su2):
    _client(manager).post(
        reverse("explorer/accounts/user-update", args=[su2.pk]),
        _admin_post(su2, as_superuser=False, is_active=False),
    )
    assert _fresh(su2).is_active


def test_g3_2_explorer_cannot_remove_a_superusers_staff_flag(manager, su2):
    _client(manager).post(
        reverse("explorer/accounts/user-update", args=[su2.pk]),
        _admin_post(su2, as_superuser=False, is_staff=False),
    )
    assert _fresh(su2).is_staff


def test_g3_2_explorer_still_changes_a_wider_accounts_flags(manager, god):
    resp = _client(manager).post(
        reverse("explorer/accounts/user-update", args=[god.pk]),
        _admin_post(god, as_superuser=False, is_active=False),
    )
    assert resp.status_code == 302
    assert not _fresh(god).is_active


def test_g3_2_explorer_cannot_delete_a_superuser(god, su2):
    """Even holding every permission (and so every cascade's delete), a
    non-superuser doesn't delete a superuser: the User Manager's rule, and
    now admin's ``has_delete_permission(obj)``, which Explorer asks."""
    _client(god).post(reverse("explorer/accounts/user-delete", args=[su2.pk]))
    assert User.objects.filter(pk=su2.pk).exists()


def test_g3_2_explorer_bulk_delete_skips_a_superuser(god, su2):
    plain = User.objects.create_user("plain2", password="pw")
    url = reverse("explorer/accounts/user-bulk")
    c = _client(god)
    c.post(url, json.dumps({"action": "delete", "ids": [su2.pk]}), content_type="application/json")
    assert User.objects.filter(pk=su2.pk).exists()
    # Control: the same request deletes an ordinary account.
    c.post(url, json.dumps({"action": "delete", "ids": [plain.pk]}), content_type="application/json")
    assert not User.objects.filter(pk=plain.pk).exists()


def test_g3_2_explorer_delete_control_a_plain_account_is_deleted(god):
    """Control for the tests above: the same POST deletes an ordinary account."""
    plain = User.objects.create_user("plain", password="pw")
    _client(god).post(reverse("explorer/accounts/user-delete", args=[plain.pk]))
    assert not User.objects.filter(pk=plain.pk).exists()
