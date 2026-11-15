"""Revoke + stats endpoints."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice", password="x")


@pytest.fixture
def bob():
    return User.objects.create_user(username="bob", password="x")


@pytest.fixture
def staff_user():
    from django.contrib.auth.models import Permission

    # Revoking someone else's token needs smallstack.change_apitoken (G2-2).
    user = User.objects.create_user(username="boss", password="x", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="smallstack", codename="change_apitoken"))
    return user


def _mint(user):
    t, _ = APIToken.create_token(user=user, name=f"{user.username}-t")
    return t


def test_revoke_get_method_not_allowed(alice):
    t = _mint(alice)
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 405


def test_revoke_anonymous_redirects(alice):
    t = _mint(alice)
    resp = Client().post(
        reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost"
    )
    assert resp.status_code in (301, 302)


def test_owner_can_revoke_own_token(alice):
    t = _mint(alice)
    assert t.is_active
    c = Client(enforce_csrf_checks=False)
    c.force_login(alice)
    resp = c.post(reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 302
    t.refresh_from_db()
    assert t.is_active is False
    assert t.revoked_at is not None


def test_non_owner_non_staff_cannot_revoke(alice, bob):
    t = _mint(alice)
    c = Client(enforce_csrf_checks=False)
    c.force_login(bob)
    resp = c.post(reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 403
    t.refresh_from_db()
    assert t.is_active is True  # untouched


def test_token_manager_can_revoke_a_members_token(alice, staff_user):
    t = _mint(alice)
    c = Client(enforce_csrf_checks=False)
    c.force_login(staff_user)
    resp = c.post(reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 302
    t.refresh_from_db()
    assert t.is_active is False


def test_revoking_already_revoked_token_is_a_noop(alice):
    t = _mint(alice)
    t.revoke()
    c = Client(enforce_csrf_checks=False)
    c.force_login(alice)
    resp = c.post(reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 302  # still redirects, no error


def test_stats_owner_sees_panel(alice):
    t = _mint(alice)
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:token-stats", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 200
    assert resp.context["token"].pk == t.pk
    assert "stats" in resp.context


def test_stats_non_owner_forbidden(alice, bob):
    t = _mint(alice)
    c = Client()
    c.force_login(bob)
    resp = c.get(reverse("tokenmgr:token-stats", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_stats_clamps_hours(alice):
    t = _mint(alice)
    c = Client()
    c.force_login(alice)
    resp = c.get(
        reverse("tokenmgr:token-stats", kwargs={"pk": t.pk}) + "?hours=99999",
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 200
    assert resp.context["selected_hours"] <= 24 * 30
