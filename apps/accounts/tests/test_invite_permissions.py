"""G2-1: the invite page creates an active account, so it asks what the User
Manager's create page asks.

Before the fix ``InviteUserView`` needed only ``is_staff``: a staff account
holding no permission at all could post ``is_staff=on`` and get a new, active
staff account whose set-password link went to an address it chose.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()

INVITE = "accounts:invite"


def _perm(codename):
    return Permission.objects.get(content_type__app_label="accounts", codename=codename)


def _staff(username, *codenames):
    user = User.objects.create_user(username, password="pw", is_staff=True)
    user.user_permissions.add(*[_perm(c) for c in codenames])
    return User.objects.get(pk=user.pk)  # a fresh instance: no stale perm cache


def test_g2_1_staff_without_add_user_cannot_invite(client):
    client.force_login(_staff("olaf"))
    assert client.get(reverse(INVITE)).status_code == 403
    resp = client.post(reverse(INVITE), {"email": "sock@acme.test", "is_staff": "on"})
    assert resp.status_code == 403
    assert not User.objects.filter(email="sock@acme.test").exists()


def test_g2_1_add_user_without_change_user_invites_a_non_staff_account(client):
    client.force_login(_staff("adder", "add_user"))
    page = client.get(reverse(INVITE))
    assert page.status_code == 200
    assert 'name="is_staff"' not in page.content.decode()  # the box isn't offered
    resp = client.post(reverse(INVITE), {"email": "new@acme.test", "is_staff": "on"})
    assert resp.status_code == 302
    invited = User.objects.get(email="new@acme.test")
    assert invited.is_staff is False  # the crafted field was ignored
    assert invited.is_superuser is False


def test_g2_1_add_and_change_user_may_invite_staff(client):
    client.force_login(_staff("manager", "add_user", "change_user"))
    assert 'name="is_staff"' in client.get(reverse(INVITE)).content.decode()
    resp = client.post(reverse(INVITE), {"email": "colleague@acme.test", "is_staff": "on"})
    assert resp.status_code == 302
    assert User.objects.get(email="colleague@acme.test").is_staff is True


def test_g2_1_an_invite_never_creates_a_superuser(client):
    admin = User.objects.create_superuser("root", password="pw")
    client.force_login(admin)
    resp = client.post(reverse(INVITE), {"email": "su@acme.test", "is_staff": "on", "is_superuser": "on"})
    assert resp.status_code == 302
    invited = User.objects.get(email="su@acme.test")
    assert invited.is_staff is True
    assert invited.is_superuser is False


def test_g2_1_user_list_hides_invite_without_add_user(client):
    invite_url = reverse(INVITE)
    # The list itself needs view_user (S2-1).
    client.force_login(_staff("olaf", "view_user"))
    assert invite_url not in client.get(reverse("manage/users-list")).content.decode()
    client.force_login(_staff("adder", "view_user", "add_user"))
    assert invite_url in client.get(reverse("manage/users-list")).content.decode()
