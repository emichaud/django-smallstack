"""TokensDashboardWidget tests."""

import pytest
from django.contrib.auth import get_user_model

from apps.smallstack.models import APIToken
from apps.tokenmgr.dashboard_widgets import TokensDashboardWidget

pytestmark = pytest.mark.django_db
User = get_user_model()


def test_empty_state():
    APIToken.objects.all().delete()
    data = TokensDashboardWidget().get_data()
    assert data["headline"] == "No tokens"
    assert data["status"] == "operational"
    assert "Mint" in data["detail"]


def test_active_only_headline():
    u = User.objects.create_user(username="x", password="x")
    APIToken.create_token(user=u, name="a")
    APIToken.create_token(user=u, name="b")
    data = TokensDashboardWidget().get_data()
    assert "2 active" in data["headline"]
    assert "of 2 total" in data["detail"]
    assert "revoked" not in data["detail"]


def test_revoked_count_in_detail():
    u = User.objects.create_user(username="x", password="x")
    t, _ = APIToken.create_token(user=u, name="a")
    t.revoke()
    APIToken.create_token(user=u, name="b")
    data = TokensDashboardWidget().get_data()
    assert "1 active" in data["headline"]
    assert "of 2 total" in data["detail"]
    assert "1 revoked" in data["detail"]


def test_api_extras_payload():
    u = User.objects.create_user(username="x", password="x")
    APIToken.create_token(user=u, name="r", access_level="readonly")
    APIToken.create_token(user=u, name="s", access_level="staff")
    APIToken.create_token(user=u, name="a", access_level="auth")
    extras = TokensDashboardWidget().get_api_extras()
    assert extras["total_tokens"] == 3
    assert extras["active_tokens"] == 3
    assert extras["revoked_tokens"] == 0
    assert extras["by_access_level"] == {"readonly": 1, "staff": 1, "auth": 1}


def test_widget_metadata():
    w = TokensDashboardWidget()
    assert w.title == "API Tokens"
    assert w.url_name == "tokenmgr:tokens-list"


def test_widget_registered_on_dashboard():
    from apps.smallstack import dashboard

    titles = [w.title for w in dashboard._standalone_widgets]
    assert "API Tokens" in titles


# --- E-dec 4 (2026-11-14 access-control round) --------------------------------
# The widget stays visible to every staff account (S2-1 left it open): it
# shows system-wide totals, and the totals are all it may show. Plain staff
# can't read other accounts' tokens (that needs smallstack.view_apitoken), so
# no token name, owner or label may reach them through the card or its API.


@pytest.fixture
def tokens_of_others():
    root = User.objects.create_superuser("rootowner-zq", password="x", email="root-zq@acme.test")
    APIToken.create_token(user=root, name="deploy-label-zq", access_level="auth")
    t, _ = APIToken.create_token(user=root, name="ci-label-zq", access_level="staff")
    t.revoke()
    return root


@pytest.fixture
def plain_staff():
    return User.objects.create_user("plainstaff", password="x", is_staff=True)


def _assert_no_names(text):
    for needle in ("rootowner-zq", "root-zq@acme.test", "deploy-label-zq", "ci-label-zq"):
        assert needle not in text, needle


def test_e_dec_4_dashboard_card_shows_totals_only_to_plain_staff(client, tokens_of_others, plain_staff, monkeypatch):
    # apps.dashboards draws /smallstack/ from a stored layout; the fixed grid
    # of registered widgets is what renders this card on every install.
    monkeypatch.setattr("apps.smallstack.views.get_dashboard_page", lambda: None)
    client.force_login(plain_staff)
    page = client.get("/smallstack/")
    assert page.status_code == 200
    body = page.content.decode()
    assert "API Tokens" in body and "1 active" in body and "of 2 total" in body
    _assert_no_names(body)


def test_e_dec_4_widget_api_payload_is_counts_only(client, tokens_of_others, plain_staff):
    import json

    from apps.smallstack.dashboard import get_widget_contexts, serialize_widget_context

    ctx = next(c for c in get_widget_contexts(user=plain_staff) if c["widget"].title == "API Tokens")
    payload = serialize_widget_context(ctx)
    assert set(payload["data"]) == {
        "headline",
        "detail",
        "status",
        "total_tokens",
        "active_tokens",
        "revoked_tokens",
        "by_access_level",
    }
    assert payload["data"]["by_access_level"] == {"readonly": 0, "staff": 1, "auth": 1}
    _assert_no_names(json.dumps(payload))

    _, raw = APIToken.create_token(user=plain_staff, name="mine", access_level="staff")
    reply = client.get("/api/dashboard/widgets/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert reply.status_code == 200
    assert "API Tokens" in [w["title"] for w in reply.json()["widgets"]]
    _assert_no_names(reply.content.decode())
