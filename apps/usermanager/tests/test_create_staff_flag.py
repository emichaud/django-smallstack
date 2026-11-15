"""D-1: the User Manager's create page follows the invite page (2026-11-14
access-control round): ticking *Staff* needs ``accounts.change_user``.

Before the fix an ``add_user`` holder could tick (or post) ``is_staff`` on
``/smallstack/manage/users/new/`` and create an active staff account, while
the invite page (G2-1) already refused the same thing.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()

NEW = "manage/users-create"
PASSWORD = "Corr3ct-horse-battery"


def _staff(username, *codenames):
    user = User.objects.create_user(username, password="pw", is_staff=True)
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="accounts", codename__in=codenames)
    )
    c = Client()
    c.force_login(User.objects.get(pk=user.pk))
    return c


def _create(client, url, username, **extra):
    data = {"username": username, "email": f"{username}@acme.test", "is_active": "on", "is_staff": "on"}
    data.update(extra)
    return client.post(url, data)


def test_d1_add_user_alone_is_not_offered_the_staff_box():
    page = _staff("adder", "view_user", "add_user").get(reverse(NEW))
    assert page.status_code == 200
    assert 'name="is_staff"' not in page.content.decode()


def test_d1_a_posted_staff_flag_is_ignored_without_change_user():
    client = _staff("adder", "view_user", "add_user")
    resp = _create(client, reverse(NEW), "sock", password1=PASSWORD, password2=PASSWORD)
    assert resp.status_code == 302
    created = User.objects.get(username="sock")
    assert created.is_staff is False
    assert created.is_superuser is False


def test_d1_add_and_change_user_may_create_staff():
    client = _staff("manager", "view_user", "add_user", "change_user")
    assert 'name="is_staff"' in client.get(reverse(NEW)).content.decode()
    resp = _create(client, reverse(NEW), "colleague", password1=PASSWORD, password2=PASSWORD)
    assert resp.status_code == 302
    assert User.objects.get(username="colleague").is_staff is True


def test_d1_explorer_create_follows_the_same_rule():
    client = _staff("adder", "view_user", "add_user")
    _create(client, reverse("explorer/accounts/user-create"), "sock2")
    assert User.objects.get(username="sock2").is_staff is False
