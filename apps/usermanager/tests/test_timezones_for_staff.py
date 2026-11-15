"""The Timezones dashboard is a team scheduling tool open to every active
staff account (E-dec 3, 2026-11-14 access-control round).

S2-1 put it behind ``accounts.view_user`` with the rest of the User Manager.
It is reopened to plain staff, so it must show them names, avatars and time
zones only: no email (not even as a search oracle), no staff badge or
*Staff only* filter, no link into the edit page. It has its own sidebar
entry, since plain staff don't see *Users*.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db
User = get_user_model()

URL = "/smallstack/manage/users/timezones/"


def _client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def olaf():
    """Staff with no permissions."""
    return User.objects.create_user("olaf", password="pw", email="olaf@acme.test", is_staff=True)


@pytest.fixture
def lee():
    user = User.objects.create_user(
        "lee", password="pw", email="lee.secret@acme.test", first_name="Lee", last_name="Ng", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Access reviewer"))
    return user


def test_plain_staff_open_it(olaf, lee):
    assert reverse("manage/users-timezones") == URL
    page = _client(olaf).get(URL)
    assert page.status_code == 200
    body = page.content.decode()
    assert "Lee Ng" in body and "olaf" in body


def test_non_staff_still_refused():
    member = User.objects.create_user("m", password="pw")
    assert _client(member).get(URL).status_code == 403


def test_nothing_about_access_for_plain_staff(olaf, lee):
    page = _client(olaf).get(URL)
    assert page.status_code == 200
    body = page.content.decode()
    assert "lee.secret@acme.test" not in body  # (olaf's own email is in his user menu)
    assert "Access reviewer" not in body
    assert ">staff</span>" not in body
    assert 'data-filter="staff"' not in body
    assert '"staff": true' not in body
    assert reverse("manage/users-update", args=[lee.pk]) not in body
    assert f'href="{reverse("manage/users-list")}"' not in body


def test_email_is_not_a_search_oracle(olaf, lee):
    c = _client(olaf)
    assert "Lee Ng" in c.get(URL, {"q": "lee"}, HTTP_HX_REQUEST="true").content.decode()
    assert "Lee Ng" not in c.get(URL, {"q": "lee.secret"}, HTTP_HX_REQUEST="true").content.decode()


def test_the_sidebar_link_shows_for_plain_staff(olaf):
    body = _client(olaf).get("/smallstack/").content.decode()
    assert f'href="{URL}"' in body


def test_guard_view_user_keeps_badge_link_and_email_search(olaf, lee):
    olaf.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
    c = _client(User.objects.get(pk=olaf.pk))
    body = c.get(URL).content.decode()
    assert ">staff</span>" in body
    assert reverse("manage/users-update", args=[lee.pk]) in body
    assert "Lee Ng" in c.get(URL, {"q": "lee.secret"}, HTTP_HX_REQUEST="true").content.decode()
