"""*Revoke tokens & sign out* on the Access user page (E-dec 1, 2026-11-14
access-control round).

The button needed ``smallstack.change_apitoken`` and the page needs
``accounts.view_user``, so no shipped group could use it: User manager can
open the page but lacked the token permission, and Token manager holds the
token permission but can't open the page. A User manager can deactivate the
account, which revokes every token and ends every session anyway, so
``accounts.change_user`` now opens the button too, with deactivation's rules:
only a superuser acts on a superuser, and nobody acts on their own account.
The button shows exactly where the POST succeeds (``revoke_all_refusal``
answers both), and every revoke is still recorded.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from apps.access.models import AccessEvent
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()

BUTTON = "Revoke tokens &amp; sign out"


def _client(user):
    c = Client(HTTP_HOST="localhost")
    c.force_login(user)
    return c


def _in(name, username):
    user = User.objects.create_user(username, password="pw", is_staff=True)
    user.groups.add(Group.objects.get(name=name))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def um():
    return _in("User manager", "um")


@pytest.fixture
def member():
    user = User.objects.create_user("member", password="pw")
    APIToken.create_token(user=user, name="a")
    APIToken.create_token(user=user, name="b")
    return user


@pytest.fixture
def wider():
    """A non-superuser holding more than the User manager (a Token manager)."""
    user = _in("Token manager", "wider")
    APIToken.create_token(user=user, name="w")
    return user


@pytest.fixture
def root():
    user = User.objects.create_superuser("root", password="pw")
    APIToken.create_token(user=user, name="r")
    return user


def _page(client, user):
    page = client.get(reverse("access:user_detail", kwargs={"pk": user.pk}))
    assert page.status_code == 200
    return page.content.decode()


def _post(client, user):
    return client.post(reverse("access:user_revoke", kwargs={"pk": user.pk}))


def test_e_dec_1_user_manager_revokes_a_members_access_and_it_is_recorded(um, member):
    c = _client(um)
    assert BUTTON in _page(c, member)
    assert _post(c, member).status_code == 302
    assert not APIToken.objects.filter(user=member, is_active=True).exists()
    events = AccessEvent.objects.filter(kind="token_revoked", subject=member)
    assert events.count() == 2 and set(events.values_list("actor", flat=True)) == {um.pk}


def test_e_dec_1_user_manager_revokes_a_wider_non_superuser_as_deactivation_allows(um, wider):
    c = _client(um)
    assert BUTTON in _page(c, wider)
    assert _post(c, wider).status_code == 302
    assert not APIToken.objects.filter(user=wider, is_active=True).exists()


def test_e_dec_1_user_manager_refused_on_a_superuser_and_on_themselves(um, root):
    APIToken.create_token(user=um, name="mine")
    c = _client(um)
    for target in (root, um):
        assert BUTTON not in _page(c, target)
        assert _post(c, target).status_code == 403
    assert APIToken.objects.filter(user=root, is_active=True).exists()
    assert APIToken.objects.filter(user=um, is_active=True).exists()


def test_e_dec_1_button_and_post_agree_for_every_persona(um, member, wider, root):
    from apps.access.services import revoke_all_refusal

    reader = _in("Access reviewer", "reader")  # view_user, neither write permission
    both = _in("User manager", "both")
    both.groups.add(Group.objects.get(name="Token manager"))
    both = User.objects.get(pk=both.pk)
    for actor in (um, reader, both, root):
        c = _client(actor)
        for target in (member, wider, root, actor):
            APIToken.create_token(user=target, name=f"t-{actor.pk}")
            shown = BUTTON in _page(c, target)
            assert shown == (not revoke_all_refusal(actor, target)), (actor, target)
            status = _post(c, target).status_code
            assert status == (302 if shown else 403), (actor, target, status)


def test_guard_staff_without_either_permission_is_refused(member):
    reader = _in("Access reviewer", "reader")
    c = _client(reader)
    assert BUTTON not in _page(c, member)
    assert _post(c, member).status_code == 403
