"""``GET /smallstack/search/api/?q=`` — the ranked search over REST.

It answers to an API token (or a session) and searches as that token's user,
through the same :func:`search_all` as the omnibar and the ``search_all`` MCP
tool, so a REST client sees exactly what that user would see there: no hits
from a staff-only view for a member, and only the rows a view's
``search_visibility`` leaves them.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.search.access import SearchAccess
from apps.search.backends import get_backend
from apps.search.registry import all_views, register, unregister
from apps.smallstack.crud import CRUDView
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()
LABEL = f"{User._meta.app_label}.{User.__name__}"


@pytest.fixture(autouse=True)
def clean_registry():
    unregister(LABEL)
    yield
    unregister(LABEL)


def _register_users(access=SearchAccess.STAFF, visibility=None) -> None:
    attrs = {
        "model": User,
        "url_base": "rest-search-test",
        "enable_search": True,
        "search_fields": ["username"],
        "search_display": "username",
        "search_access": access,
    }
    if visibility is not None:
        attrs["search_visibility"] = staticmethod(visibility)
    register(type("RestSearchUserView", (CRUDView,), attrs))


def _index() -> None:
    for view in all_views():
        get_backend().rebuild(view)


def _get(client, user, **params):
    _token, raw = APIToken.create_token(user=user, name="rest-search-test")
    return client.get(reverse("search:api"), params, HTTP_AUTHORIZATION=f"Bearer {raw}")


def test_it_needs_a_token_or_a_session(client):
    assert client.get(reverse("search:api"), {"q": "x"}).status_code == 401


def test_a_staff_token_finds_staff_only_rows(client):
    _register_users()
    User.objects.create_user("needle-rest-zz")
    _index()
    staff = User.objects.create_user("rest-staff", password="x", is_staff=True)
    body = _get(client, staff, q="needle-rest-zz").json()
    assert [r["display"] for r in body["results"]] == ["needle-rest-zz"]
    assert body["count"] == 1 and body["results"][0]["model_label"] == LABEL


def test_a_member_token_gets_nothing_from_a_staff_only_view(client):
    _register_users()
    User.objects.create_user("needle-rest-zz")
    _index()
    member = User.objects.create_user("rest-member", password="x")
    assert _get(client, member, q="needle-rest-zz").json()["results"] == []


def test_visibility_narrows_a_member_to_their_own_rows(client):
    _register_users(SearchAccess.AUTHENTICATED, visibility=lambda qs, user: qs.filter(pk=user.pk))
    mine = User.objects.create_user("needle-mine-zz", password="x")
    User.objects.create_user("needle-theirs-zz")
    _index()
    names = [r["display"] for r in _get(client, mine, q="needle").json()["results"] if r["model_label"] == LABEL]
    assert names == ["needle-mine-zz"]


def test_model_narrows_to_one_label_and_limit_caps_the_list(client):
    _register_users()
    for i in range(4):
        User.objects.create_user(f"needle-many-{i}-zz")
    _index()
    staff = User.objects.create_user("rest-staff2", password="x", is_staff=True)
    body = _get(client, staff, q="needle-many", model=LABEL.lower(), limit=2).json()
    assert body["count"] == 2 and {r["model_label"] for r in body["results"]} == {LABEL}
    assert _get(client, staff, q="needle-many", model="nope.Nothing").json()["results"] == []


@pytest.mark.parametrize("limit", ["0", "51", "many"])
def test_a_bad_limit_is_refused(client, limit):
    staff = User.objects.create_user("rest-staff3", password="x", is_staff=True)
    resp = _get(client, staff, q="x", limit=limit)
    assert resp.status_code == 400 and "limit" in str(resp.json())


def test_no_query_lists_what_may_be_searched(client):
    _register_users()
    staff = User.objects.create_user("rest-staff4", password="x", is_staff=True)
    body = _get(client, staff).json()
    assert body["query"] == "" and body["results"] == []
    assert any(s.get("model_label") == LABEL for s in body["sources"]), body["sources"]


def test_it_is_in_the_openapi_schema(client):
    staff = User.objects.create_user("rest-staff5", password="x", is_staff=True)
    client.force_login(staff)
    schema = client.get("/api/schema/openapi.json").json()
    op = schema["paths"][reverse("search:api")]["get"]
    assert {p["name"] for p in op["parameters"]} >= {"q", "limit", "model"}
