"""The /api/auth/users/* endpoints are bounded by the token's owner (G1-2, 2026-11-14 round).

They checked only that the token was auth-level, so a non-staff member holding
one could deactivate a superuser and make herself staff, and a Token manager
could raise their own token to ``auth`` in Explorer and do the same.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings

from apps.access.models import AccessEvent
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


def _grant(user, *codenames):
    for c in codenames:
        user.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename=c))
    return User.objects.get(pk=user.pk)


def _hdr(user):
    _, raw = APIToken.create_token(user, name="auth", token_type="manual", access_level="auth")
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def _patch(user_id, payload, hdr):
    return Client().patch(
        f"/api/auth/users/{user_id}/", data=json.dumps(payload), content_type="application/json", **hdr
    )


@pytest.fixture
def root():
    return User.objects.create_superuser(username="root", password="x", email="r@x")


@pytest.fixture
def victim():
    return User.objects.create_user(username="victim", password="x")


@pytest.fixture
def mia():
    return User.objects.create_user(username="mia", password="x")


@pytest.fixture
def plain_staff():
    return User.objects.create_user(username="olaf", password="x", is_staff=True)


@pytest.fixture
def um():
    u = User.objects.create_user(username="um", password="x", is_staff=True)
    return _grant(u, "add_user", "change_user", "view_user")


def test_g1_2_non_staff_owner_is_refused(mia, root):
    hdr = _hdr(mia)
    assert _patch(mia.pk, {"is_staff": True}, hdr).status_code == 403
    assert Client().post(f"/api/auth/users/{root.pk}/deactivate/", **hdr).status_code == 403
    mia.refresh_from_db()
    root.refresh_from_db()
    assert not mia.is_staff
    assert root.is_active


def test_g1_2_staff_without_change_user_is_refused(plain_staff, victim):
    hdr = _hdr(plain_staff)
    assert _patch(victim.pk, {"is_staff": True}, hdr).status_code == 403
    assert Client().post(f"/api/auth/users/{victim.pk}/deactivate/", **hdr).status_code == 403
    resp = Client().post(
        f"/api/auth/users/{victim.pk}/password/",
        data=json.dumps({"new_password": "N3w-Str0ng-pass!"}),
        content_type="application/json",
        **hdr,
    )
    assert resp.status_code == 403
    victim.refresh_from_db()
    assert not victim.is_staff and victim.is_active
    assert victim.check_password("x")


@override_settings(SMALLSTACK_API_REGISTER_ENABLED=True)
def test_g1_2_register_needs_add_user(plain_staff):
    resp = Client().post(
        "/api/auth/register/",
        data=json.dumps({"username": "newbie", "password": "N3w-Str0ng-pass!"}),
        content_type="application/json",
        **_hdr(plain_staff),
    )
    assert resp.status_code == 403
    assert not User.objects.filter(username="newbie").exists()


def test_g1_2_user_manager_may_change_a_member_not_a_superuser(um, victim, root):
    hdr = _hdr(um)
    assert _patch(victim.pk, {"is_staff": True}, hdr).status_code == 200
    assert Client().post(f"/api/auth/users/{root.pk}/deactivate/", **hdr).status_code == 403
    assert _patch(root.pk, {"email": "x@y"}, hdr).status_code == 403
    victim.refresh_from_db()
    root.refresh_from_db()
    assert victim.is_staff
    assert root.is_active and root.email == "r@x"


def test_g1_2_superuser_may_change_a_superuser(root):
    other = User.objects.create_superuser(username="root2", password="x", email="r2@x")
    assert Client().post(f"/api/auth/users/{other.pk}/deactivate/", **_hdr(root)).status_code == 200


def test_g1_2_changes_record_the_token_owner_as_actor(um, victim):
    Client().post(f"/api/auth/users/{victim.pk}/deactivate/", **_hdr(um))
    event = AccessEvent.objects.filter(kind="deactivated", subject=victim).latest("pk")
    assert event.actor == um
    assert event.source == f"rest:/api/auth/users/{victim.pk}/deactivate/"


def test_g1_2_token_access_level_is_read_only_after_creation():
    from django.contrib import admin

    from apps.smallstack.admin import APITokenExplorerForm

    tm = User.objects.create_user(username="tm", password="x", is_staff=True)
    token, _ = APIToken.create_token(tm, name="mine", access_level="staff")
    form = APITokenExplorerForm(
        data={"name": "mine", "user": tm.pk, "token_type": "manual", "access_level": "auth", "is_active": True},
        instance=token,
    )
    assert form.is_valid(), form.errors
    form.save()
    token.refresh_from_db()
    assert token.access_level == "staff"
    model_admin = admin.site._registry[APIToken]
    assert "access_level" in model_admin.get_readonly_fields(None, token)
