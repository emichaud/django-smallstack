"""Who may mint a token owned by someone else (G1-1, 2026-11-14 access-control round).

Whoever holds a token acts as its owner, so minting one for another account
hands the minter that account. Any staff account could mint for a superuser
and read the raw key from the reveal page.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client
from django.urls import reverse

from apps.smallstack.models import APIToken
from apps.tokenmgr.forms import TokenCreateForm, mintable_users

pytestmark = pytest.mark.django_db
User = get_user_model()


def _perm(label):
    app, codename = label.split(".")
    return Permission.objects.get(content_type__app_label=app, codename=codename)


@pytest.fixture
def root():
    return User.objects.create_superuser(username="root", password="x", email="r@x")


@pytest.fixture
def olaf():
    """Plain staff, no permissions."""
    return User.objects.create_user(username="olaf", password="x", is_staff=True)


@pytest.fixture
def tess():
    """A token manager: staff + the token permissions."""
    u = User.objects.create_user(username="tess", password="x", is_staff=True)
    for p in ("smallstack.add_apitoken", "smallstack.view_apitoken", "smallstack.change_apitoken"):
        u.user_permissions.add(_perm(p))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def worker():
    """Staff, holding only a permission tess also holds."""
    u = User.objects.create_user(username="worker", password="x", is_staff=True)
    u.user_permissions.add(_perm("smallstack.view_apitoken"))
    return u


@pytest.fixture
def um():
    """Holds a permission tess lacks, through a group."""
    u = User.objects.create_user(username="um", password="x", is_staff=True)
    g = Group.objects.create(name="Accounts")
    g.permissions.add(_perm("accounts.change_user"))
    u.groups.add(g)
    return u


def _post(minter, owner, level="staff"):
    c = Client()
    c.force_login(minter)
    return c.post(
        reverse("tokenmgr:token-create"),
        {"user": owner.pk, "name": "probe", "access_level": level},
        HTTP_HOST="localhost",
    )


def test_g1_1_plain_staff_cannot_mint_for_a_superuser(olaf, root):
    resp = _post(olaf, root)
    assert resp.status_code == 200  # the form again, with an error
    assert not APIToken.objects.filter(user=root).exists()


def test_g1_1_token_manager_cannot_mint_for_superuser_or_a_wider_account(tess, root, um):
    _post(tess, root)
    _post(tess, um)
    assert not APIToken.objects.filter(user__in=[root, um]).exists()


def test_g1_1_token_manager_may_mint_for_an_account_within_their_permissions(tess, worker):
    resp = _post(tess, worker)
    assert resp.status_code == 302
    assert APIToken.objects.filter(user=worker, access_level="staff").exists()


def test_g1_1_without_add_apitoken_only_self(olaf, worker):
    _post(olaf, worker, level="readonly")
    assert not APIToken.objects.filter(user=worker).exists()
    assert _post(olaf, olaf).status_code == 302


def test_g1_1_only_a_superuser_chooses_auth(tess, worker, root):
    form = TokenCreateForm(data={"name": "t", "user": worker.pk, "access_level": "auth"}, request_user=tess)
    assert not form.is_valid()
    assert "access_level" in form.errors
    ok = TokenCreateForm(data={"name": "t", "user": worker.pk, "access_level": "auth"}, request_user=root)
    assert ok.is_valid(), ok.errors


def test_g1_1_picker_lists_only_pickable_accounts(olaf, tess, worker, um, root):
    assert set(mintable_users(olaf)) == {olaf}
    assert set(mintable_users(tess)) == {tess, worker, olaf}  # olaf holds nothing tess lacks
    assert set(mintable_users(root)) >= {olaf, tess, worker, um, root}
    assert TokenCreateForm(request_user=olaf).fields["user"].widget.__class__.__name__ == "HiddenInput"
    assert set(TokenCreateForm(request_user=tess).fields["user"].queryset) == {tess, worker, olaf}


def test_g1_1_clean_refuses_even_when_the_choice_is_offered(tess, worker):
    """Server-side, not only in the choices: widen the queryset, the rule still holds."""
    form = TokenCreateForm(
        data={"name": "t", "user": worker.pk, "access_level": "staff"}, request_user=tess
    )
    worker.user_permissions.add(_perm("accounts.delete_user"))  # now wider than tess
    form.fields["user"].queryset = User.objects.all()
    assert not form.is_valid()
    assert "user" in form.errors
