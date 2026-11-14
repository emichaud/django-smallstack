"""Auth API endpoints — register, own-password change, admin password reset.

Covers the previously-untested security endpoints in api.py (review F4):
`api_auth_register`, `api_auth_password`, `api_auth_user_password`.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()

_NEW_PW = "N3w-Str0ng-pass!"


def _auth_token_header(user) -> dict[str, str]:
    _, raw = APIToken.create_token(user, name="auth", token_type="manual", access_level="auth")
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def _post(client, url, payload, **headers):
    return client.post(url, data=json.dumps(payload), content_type="application/json", **headers)


@pytest.fixture
def admin():
    return User.objects.create_user(username="adminx", password="oldpass1234", is_staff=True)


# --- register ---------------------------------------------------------------


def test_register_get_is_405(client):
    assert client.get("/api/auth/register/").status_code == 405


def test_register_requires_auth_level_token(client, admin):
    # A staff-level token authenticates but isn't auth-level → 403.
    _, raw = APIToken.create_token(admin, name="staff", access_level="staff")
    r = _post(client, "/api/auth/register/", {"username": "n", "password": _NEW_PW},
              HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert r.status_code == 403


@override_settings(SMALLSTACK_API_REGISTER_ENABLED=False)
def test_register_disabled_is_403(client, admin):
    r = _post(client, "/api/auth/register/", {"username": "alice", "password": _NEW_PW},
              **_auth_token_header(admin))
    assert r.status_code == 403


@override_settings(SMALLSTACK_API_REGISTER_ENABLED=True)
def test_register_creates_user(client, admin):
    r = _post(client, "/api/auth/register/",
              {"username": "alice", "password": _NEW_PW, "email": "alice@example.com"},
              **_auth_token_header(admin))
    assert r.status_code in (200, 201)
    assert User.objects.filter(username="alice").exists()


# --- own password change ----------------------------------------------------


def test_password_change_wrong_current_is_400(client):
    u = User.objects.create_user(username="pwuser", password="oldpass1234")
    client.force_login(u)
    r = _post(client, "/api/auth/password/", {"current_password": "WRONG", "new_password": _NEW_PW})
    assert r.status_code == 400


def test_password_change_missing_fields_is_400(client):
    u = User.objects.create_user(username="pwuser0", password="oldpass1234")
    client.force_login(u)
    assert _post(client, "/api/auth/password/", {"current_password": "oldpass1234"}).status_code == 400


def test_password_change_success(client):
    u = User.objects.create_user(username="pwuser2", password="oldpass1234")
    client.force_login(u)
    r = _post(client, "/api/auth/password/",
              {"current_password": "oldpass1234", "new_password": _NEW_PW})
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.check_password(_NEW_PW)


# --- admin password reset (auth-level token) --------------------------------


def test_user_password_reset_requires_auth_token(client):
    target = User.objects.create_user(username="target", password="oldpass1234")
    # No credentials → 401 (authentication required).
    r = _post(client, f"/api/auth/users/{target.pk}/password/", {"new_password": _NEW_PW})
    assert r.status_code == 401


def test_user_password_reset_success(client, admin):
    target = User.objects.create_user(username="target2", password="oldpass1234")
    r = _post(client, f"/api/auth/users/{target.pk}/password/", {"new_password": _NEW_PW},
              **_auth_token_header(admin))
    assert r.status_code == 200
    target.refresh_from_db()
    assert target.check_password(_NEW_PW)


def test_user_password_reset_unknown_user_is_404(client, admin):
    r = _post(client, "/api/auth/users/999999/password/", {"new_password": _NEW_PW},
              **_auth_token_header(admin))
    assert r.status_code == 404
