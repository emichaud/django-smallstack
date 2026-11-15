"""G2-2: who may revoke a token, and that every revoke is recorded.

Before the fix ``TokenRevokeView`` asked only ``is_owner_or_staff``, so a staff
account holding no permissions could revoke every integration's and the
superuser's tokens, and nothing recorded who did it.
"""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.access.models import AccessEvent
from apps.smallstack.admin import APITokenExplorerForm
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()
REVOKED = AccessEvent.Kind.TOKEN_REVOKED


def _staff(username, *perms):
    user = User.objects.create_user(username=username, password="x", is_staff=True)
    for label in perms:
        app, codename = label.split(".")
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def root():
    return User.objects.create_superuser(username="root", password="x", email="r@x")


@pytest.fixture
def olaf():
    return _staff("olaf")  # staff, no permissions


@pytest.fixture
def tess():
    return _staff("tess", "smallstack.view_apitoken", "smallstack.change_apitoken")  # a Token manager


@pytest.fixture
def mia():
    return User.objects.create_user(username="mia", password="x")


def _mint(user, name=None):
    token, _ = APIToken.create_token(user=user, name=name or f"{user.username}-t")
    return token


def _post_revoke(actor, token):
    client = Client()
    client.force_login(actor)
    return client.post(reverse("tokenmgr:token-revoke", kwargs={"pk": token.pk}), HTTP_HOST="localhost")


def _revoked_events(token):
    return AccessEvent.objects.filter(kind=REVOKED, detail__token_id=token.pk)


def test_g2_2_staff_without_change_apitoken_cannot_revoke_others(olaf, mia, root):
    for token in (_mint(mia), _mint(root)):
        assert _post_revoke(olaf, token).status_code == 403
        token.refresh_from_db()
        assert token.is_active is True
        assert not _revoked_events(token).exists()


def test_g2_2_token_manager_revokes_a_members_token_and_it_is_recorded(tess, mia):
    token = _mint(mia)
    assert _post_revoke(tess, token).status_code == 302
    token.refresh_from_db()
    assert token.is_active is False
    (event,) = _revoked_events(token)
    assert event.actor == tess
    assert event.subject == mia
    assert event.source.startswith("web:/")


def test_g2_2_only_a_superuser_revokes_a_superusers_token(tess, root):
    token = _mint(root)
    assert _post_revoke(tess, token).status_code == 403
    token.refresh_from_db()
    assert token.is_active is True
    other_root = User.objects.create_superuser(username="root2", password="x", email="r2@x")
    assert _post_revoke(other_root, token).status_code == 302
    token.refresh_from_db()
    assert token.is_active is False
    assert _revoked_events(token).get().actor == other_root


def test_g2_2_anyone_revokes_their_own_token_and_it_is_recorded(olaf, mia):
    for owner in (olaf, mia):
        token = _mint(owner)
        assert _post_revoke(owner, token).status_code == 302
        token.refresh_from_db()
        assert token.is_active is False
        assert _revoked_events(token).get().actor == owner


def test_g2_2_revoke_buttons_hidden_where_the_post_would_fail(olaf, tess, mia, root):
    mia_token, root_token = _mint(mia), _mint(root)
    revoke = lambda t: reverse("tokenmgr:token-revoke", kwargs={"pk": t.pk})  # noqa: E731
    client = Client()
    client.force_login(olaf)
    listing = client.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost").content.decode()
    assert revoke(mia_token) not in listing and revoke(root_token) not in listing
    detail = client.get(reverse("tokenmgr:tokens-detail", kwargs={"pk": mia_token.pk}), HTTP_HOST="localhost")
    assert revoke(mia_token) not in detail.content.decode()
    client.force_login(tess)
    listing = client.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost").content.decode()
    assert revoke(mia_token) in listing and revoke(root_token) not in listing


def test_g2_2_access_revoke_all_refuses_a_superuser_target_for_a_non_superuser(tess, root):
    token = _mint(root)
    client = Client()
    client.force_login(tess)
    assert client.post(reverse("access:user_revoke", kwargs={"pk": root.pk}), HTTP_HOST="localhost").status_code == 403
    token.refresh_from_db()
    assert token.is_active is True


def test_g2_2_access_revoke_all_records_one_event_per_token(tess, mia):
    tokens = [_mint(mia, "a"), _mint(mia, "b")]
    client = Client()
    client.force_login(tess)
    assert client.post(reverse("access:user_revoke", kwargs={"pk": mia.pk}), HTTP_HOST="localhost").status_code == 302
    for token in tokens:
        assert _revoked_events(token).get().actor == tess  # once, not twice


def test_g2_2_admin_action_needs_change_and_skips_superuser_tokens(tess, mia, root):
    from django.contrib.admin.sites import site

    mia_token, root_token = _mint(mia), _mint(root)
    assert site._registry[APIToken].revoke_tokens.allowed_permissions == ["change"]

    client = Client()
    tess.user_permissions.add(Permission.objects.get(content_type__app_label="smallstack", codename="view_apitoken"))
    client.force_login(tess)
    resp = client.post(
        reverse("admin:smallstack_apitoken_changelist"),
        {"action": "revoke_tokens", "_selected_action": [mia_token.pk, root_token.pk]},
        HTTP_HOST="localhost",
    )
    assert resp.status_code == 302
    mia_token.refresh_from_db()
    root_token.refresh_from_db()
    assert mia_token.is_active is False and root_token.is_active is True
    assert _revoked_events(mia_token).get().actor == tess


def test_g2_2_explorer_form_locks_is_active_on_a_superusers_token(tess, root, mia):
    assert APITokenExplorerForm(instance=_mint(root), user=tess).fields["is_active"].disabled is True
    assert APITokenExplorerForm(instance=_mint(root), user=root).fields["is_active"].disabled is False
    assert APITokenExplorerForm(instance=_mint(mia), user=tess).fields["is_active"].disabled is False


def test_g2_2_a_change_form_revoke_is_recorded(tess, mia):
    token = _mint(mia)
    token.is_active = False
    token.save()
    assert _revoked_events(token).count() == 1
    token.save(update_fields=["last_used_at"])  # a usage stamp records nothing
    assert _revoked_events(token).count() == 1


def test_g2_2_sc_token_revoke_is_recorded(mia):
    token = _mint(mia)
    call_command("sc", "token", "revoke", token.prefix, stdout=StringIO())
    token.refresh_from_db()
    assert token.is_active is False
    assert token.revoked_at is not None
    assert _revoked_events(token).get().source == "shell"


def test_g2_2_rest_logout_is_recorded(mia):
    token, raw = APIToken.create_token(user=mia, name="login", token_type="login")
    resp = Client().post("/api/auth/logout/", HTTP_AUTHORIZATION=f"Bearer {raw}", HTTP_HOST="localhost")
    assert resp.status_code == 200
    event = _revoked_events(token).get()
    assert event.actor == mia
    assert event.source.startswith("rest:")
