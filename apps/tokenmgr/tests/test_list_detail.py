"""List + detail views — auth gating and per-row ownership."""

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
    return User.objects.create_user(username="boss", password="x", is_staff=True)


def _mint(user, **kwargs):
    kwargs.setdefault("name", f"{user.username}-test")
    kwargs.setdefault("access_level", "readonly")
    token, _raw = APIToken.create_token(user=user, **kwargs)
    return token


def test_list_anonymous_redirects_to_login():
    resp = Client().get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    assert resp.status_code in (301, 302)


def test_list_non_staff_sees_only_their_tokens(alice, bob):
    _mint(alice, name="alice-1")
    _mint(alice, name="alice-2")
    _mint(bob, name="bob-1")
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    assert resp.status_code == 200
    names = [t.name for t in resp.context["object_list"]]
    assert "alice-1" in names
    assert "alice-2" in names
    assert "bob-1" not in names


def test_list_staff_sees_every_token(alice, bob, staff_user):
    _mint(alice, name="alice-token")
    _mint(bob, name="bob-token")
    c = Client()
    c.force_login(staff_user)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    names = [t.name for t in resp.context["object_list"]]
    assert "alice-token" in names
    assert "bob-token" in names


def test_list_overview_stats_scoped_for_non_staff(alice, bob):
    _mint(alice, name="alice-a")
    _mint(alice, name="alice-b")
    _mint(bob, name="bob-a")
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    stats = resp.context["overview_stats"]
    assert stats["total_tokens"] == 2  # only alice's


def test_list_overview_stats_global_for_staff(alice, bob, staff_user):
    _mint(alice)
    _mint(bob)
    c = Client()
    c.force_login(staff_user)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    assert resp.context["overview_stats"]["total_tokens"] == 2


def test_detail_owner_can_view(alice):
    t = _mint(alice)
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:tokens-detail", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 200


def test_detail_non_owner_non_staff_is_forbidden(alice, bob):
    t = _mint(alice)
    c = Client()
    c.force_login(bob)
    resp = c.get(reverse("tokenmgr:tokens-detail", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 403


def test_detail_staff_can_view_any(alice, staff_user):
    t = _mint(alice)
    c = Client()
    c.force_login(staff_user)
    resp = c.get(reverse("tokenmgr:tokens-detail", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert resp.status_code == 200


def test_detail_renders_usage_panel(alice):
    t = _mint(alice)
    c = Client()
    c.force_login(alice)
    resp = c.get(reverse("tokenmgr:tokens-detail", kwargs={"pk": t.pk}), HTTP_HOST="localhost")
    assert "token_stats" in resp.context
    assert "Usage" in resp.content.decode()


# --- F-27: every single-object surface, not just the detail page ------------
#
# The related-tab route returned 200 with another user's token activity (which
# endpoints that token calls, and when) while the detail page beside it
# correctly returned 403 — because ownership was injected into the `get_object`
# of ONE of the five generated single-object bases. It now lives in
# `check_object_permission`, which the base applies to all five.


def _related_tab_url(token):
    return reverse("tokenmgr:tokens-related-tab", kwargs={"pk": token.pk, "accessor": "request_logs"})


def test_related_tab_refuses_another_users_token(client, alice, bob):
    """The reported leak. Must 403, like the detail page one route over."""
    bobs_token = _mint(bob)
    client.force_login(alice)
    resp = client.get(_related_tab_url(bobs_token))
    assert resp.status_code == 403, (
        f"cross-user token activity leaked: HTTP {resp.status_code}, "
        f"{len(resp.content)} bytes"
    )


def test_related_tab_still_works_for_the_owner(client, alice):
    """Negative control — closing the hole must not close the feature."""
    own = _mint(alice)
    client.force_login(alice)
    assert client.get(_related_tab_url(own)).status_code == 200


def test_related_tab_works_for_staff(client, alice, staff_user):
    own = _mint(alice)
    client.force_login(staff_user)
    assert client.get(_related_tab_url(own)).status_code == 200


def test_owner_can_still_reach_a_revoked_token(client, alice):
    """Why tokenmgr opts out of the queryset scoper at all.

    `get_list_queryset` hides revoked tokens from the *list* by default; if the
    detail surfaces inherited it, your own revoked token would 404.
    """
    revoked = _mint(alice, name="revoked-one")
    revoked.is_active = False
    revoked.save(update_fields=["is_active"])
    client.force_login(alice)
    detail = reverse("tokenmgr:tokens-detail", kwargs={"pk": revoked.pk})
    assert client.get(detail).status_code == 200
    assert client.get(_related_tab_url(revoked)).status_code == 200


def test_every_single_object_surface_refuses_another_users_token(client, alice, bob):
    """The generic property: enumerate the routes rather than trusting one."""
    bobs_token = _mint(bob)
    client.force_login(alice)
    results = {}
    for name, kwargs in [
        ("tokenmgr:tokens-detail", {"pk": bobs_token.pk}),
        ("tokenmgr:tokens-update", {"pk": bobs_token.pk}),
        ("tokenmgr:tokens-delete", {"pk": bobs_token.pk}),
        ("tokenmgr:tokens-related-tab", {"pk": bobs_token.pk, "accessor": "request_logs"}),
        ("tokenmgr:tokens-field-preview", {"pk": bobs_token.pk, "field_name": "name"}),
    ]:
        try:
            url = reverse(name, kwargs=kwargs)
        except Exception:  # route not generated for this view
            continue
        results[name] = client.get(url).status_code
    assert results, "no single-object routes found — test is vacuous"
    leaked = {k: v for k, v in results.items() if v == 200}
    assert not leaked, f"these surfaces leaked another user's token: {leaked} (all: {results})"
