"""G2-3: changing another account's password, email or username, or sending it
a password link, follows the subset rule (2026-11-14 access-control round).

Before the fix a *User manager* (staff + ``change_user``) could set the
password of a non-superuser holding every permission, or point its email at
an address they control and send the reset link, and then sign in as it. Only
a superuser target was protected. The rule now matches group membership and
minting: the actor must hold every permission the target holds.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()

USER_MANAGER = ["view_user", "add_user", "change_user"]


def _fresh(user):
    return User.objects.get(pk=user.pk)


@pytest.fixture
def manager():
    user = User.objects.create_user("uma", password="pw", email="uma@acme.test", is_staff=True)
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="accounts", codename__in=USER_MANAGER)
    )
    return _fresh(user)


@pytest.fixture
def god():
    """A non-superuser holding every permission."""
    user = User.objects.create_user("god", password="pw", email="god@acme.test", is_staff=True)
    user.user_permissions.add(*Permission.objects.all())
    return _fresh(user)


@pytest.fixture
def narrow():
    user = User.objects.create_user("kim", password="pw", email="kim@acme.test")
    user.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    return _fresh(user)


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def _account_post(target, **changes):
    data = {
        "username": target.username,
        "email": target.email,
        "first_name": target.first_name,
        "last_name": target.last_name,
        "is_active": "on" if target.is_active else "",
    }
    if target.is_staff:
        data["is_staff"] = "on"
    data.update(changes)
    return {k: v for k, v in data.items() if v != ""}


def _auth_header(user):
    _, raw = APIToken.create_token(user, name="auth", token_type="manual", access_level="auth")
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


# --- User Manager --------------------------------------------------------------


def test_g2_3_user_manager_cannot_change_a_wider_accounts_email(manager, god):
    resp = _client(manager).post(
        reverse("manage/users-update", args=[god.pk]), _account_post(god, email="mine@evil.test")
    )
    assert resp.status_code == 403
    assert "permission" in resp.content.decode()
    assert _fresh(god).email == "god@acme.test"


def test_g2_3_user_manager_cannot_rename_a_wider_account(manager, god):
    resp = _client(manager).post(reverse("manage/users-update", args=[god.pk]), _account_post(god, username="g0d"))
    assert resp.status_code == 403
    assert _fresh(god).username == "god"


def test_g2_3_edit_page_locks_the_fields_and_says_why(manager, god):
    page = _client(manager).get(reverse("manage/users-update", args=[god.pk])).content.decode()
    assert "acts with all of its permissions" in page
    assert reverse("manage/users-send-link", args=[god.pk]) not in page


def test_g2_3_user_manager_may_still_edit_a_wider_accounts_name(manager, god):
    resp = _client(manager).post(reverse("manage/users-update", args=[god.pk]), _account_post(god, first_name="G"))
    assert resp.status_code == 302
    assert _fresh(god).first_name == "G"


def test_g2_3_user_manager_may_change_a_narrower_accounts_email(manager, narrow):
    resp = _client(manager).post(
        reverse("manage/users-update", args=[narrow.pk]), _account_post(narrow, email="kim2@acme.test")
    )
    assert resp.status_code == 302
    assert _fresh(narrow).email == "kim2@acme.test"


def test_g2_3_user_manager_cannot_send_a_wider_account_a_link(manager, god):
    mail.outbox.clear()
    resp = _client(manager).post(reverse("manage/users-send-link", args=[god.pk]))
    assert resp.status_code == 403
    assert mail.outbox == []


def test_g2_3_user_manager_may_send_a_narrower_account_a_link(manager, narrow):
    mail.outbox.clear()
    resp = _client(manager).post(reverse("manage/users-send-link", args=[narrow.pk]))
    assert resp.status_code == 302
    assert len(mail.outbox) == 1


def test_g2_3_an_inactive_wider_account_is_still_refused(manager, god):
    """Deactivated, it holds nothing for has_perm; reactivated, it holds it all again."""
    god.is_active = False
    god.save()
    mail.outbox.clear()
    assert _client(manager).post(reverse("manage/users-send-link", args=[god.pk])).status_code == 403


def test_g2_3_your_own_account_is_unaffected(manager):
    resp = _client(manager).post(
        reverse("manage/users-update", args=[manager.pk]), _account_post(manager, email="uma2@acme.test")
    )
    assert resp.status_code == 302
    assert _fresh(manager).email == "uma2@acme.test"


# --- REST ----------------------------------------------------------------------


def test_g2_3_rest_password_of_a_wider_account_is_refused_with_the_reason(manager, god):
    resp = Client().post(
        f"/api/auth/users/{god.pk}/password/",
        data=json.dumps({"new_password": "Tak3over!pass"}),
        content_type="application/json",
        **_auth_header(manager),
    )
    assert resp.status_code == 403
    assert "permission" in resp.json()["errors"]["__all__"][0]
    assert _fresh(god).check_password("pw")


def test_g2_3_rest_password_of_a_narrower_account_works(manager, narrow):
    resp = Client().post(
        f"/api/auth/users/{narrow.pk}/password/",
        data=json.dumps({"new_password": "N3w!password-ok"}),
        content_type="application/json",
        **_auth_header(manager),
    )
    assert resp.status_code == 200
    assert _fresh(narrow).check_password("N3w!password-ok")


def test_g2_3_rest_patch_email_of_a_wider_account_is_refused(manager, god):
    hdr = _auth_header(manager)
    url = f"/api/auth/users/{god.pk}/"
    resp = Client().patch(url, data=json.dumps({"email": "mine@evil.test"}), content_type="application/json", **hdr)
    assert resp.status_code == 403
    assert _fresh(god).email == "god@acme.test"
    # Other fields are still the User manager's to change.
    resp = Client().patch(url, data=json.dumps({"first_name": "G"}), content_type="application/json", **hdr)
    assert resp.status_code == 200
    assert _fresh(god).first_name == "G"


# --- Django admin and Explorer -------------------------------------------------


def test_g2_3_admin_password_form_refuses_a_wider_account(manager, god):
    c = _client(manager)
    url = reverse("admin:auth_user_password_change", args=[god.pk])
    assert c.get(url).status_code == 403
    resp = c.post(url, {"password1": "Tak3over!pass", "password2": "Tak3over!pass", "usable_password": "true"})
    assert resp.status_code == 403
    assert _fresh(god).check_password("pw")


def test_g2_3_admin_makes_username_and_email_read_only(manager, god, narrow, rf):
    from django.contrib import admin

    model_admin = admin.site._registry[User]
    request = rf.get("/")
    request.user = manager
    assert {"username", "email"} <= set(model_admin.get_readonly_fields(request, god))
    assert not {"username", "email"} & set(model_admin.get_readonly_fields(request, narrow))


def test_g2_3_explorer_edit_keeps_a_wider_accounts_email(manager, god):
    _client(manager).post(
        reverse("explorer/accounts/user-update", args=[god.pk]), _account_post(god, email="mine@evil.test")
    )
    assert _fresh(god).email == "god@acme.test"


def test_g2_3_explorer_edit_changes_a_narrower_accounts_email(manager, narrow):
    resp = _client(manager).post(
        reverse("explorer/accounts/user-update", args=[narrow.pk]), _account_post(narrow, email="kim3@acme.test")
    )
    assert resp.status_code == 302
    assert _fresh(narrow).email == "kim3@acme.test"


# --- sc CLI --------------------------------------------------------------------


def test_g2_3_sc_follows_the_rule_and_still_works_for_a_superuser(manager, god, narrow):
    from django.core.management import call_command

    root = User.objects.create_superuser("root", password="pw")
    call_command("sc", "set", "accounts.user", str(narrow.pk), "--email=kim9@acme.test", "--user", root.username)
    assert _fresh(narrow).email == "kim9@acme.test"
    call_command("sc", "set", "accounts.user", str(god.pk), "--email=mine@evil.test", "--user", manager.username)
    assert _fresh(god).email == "god@acme.test"
    call_command("sc", "new", "accounts.user", "--username=neo", "--is_staff=true", "--user", root.username)
    assert User.objects.get(username="neo").is_staff is True
