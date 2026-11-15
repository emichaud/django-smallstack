"""List toolbar — search + filter integration."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff():
    """Staff holding smallstack.view_apitoken: sees every account's tokens (S2-1)."""
    from django.contrib.auth.models import Permission

    user = User.objects.create_user(username="boss", password="x", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="smallstack", codename="view_apitoken"))
    return user


@pytest.fixture
def alice():
    return User.objects.create_user(username="alice", password="x")


def test_search_query_filters_by_name(staff, alice):
    APIToken.create_token(user=alice, name="ci-bot")
    APIToken.create_token(user=alice, name="claude-desktop")
    APIToken.create_token(user=alice, name="github-actions")

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list") + "?q=claude", HTTP_HOST="localhost")
    names = [t.name for t in resp.context["object_list"]]
    assert names == ["claude-desktop"]


def test_is_active_filter_narrows_to_revoked(staff, alice):
    t, _ = APIToken.create_token(user=alice, name="will-revoke")
    t.revoke()
    APIToken.create_token(user=alice, name="still-active")

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list") + "?is_active=false", HTTP_HOST="localhost")
    statuses = [t.is_active for t in resp.context["object_list"]]
    assert statuses == [False]


def test_access_level_filter_narrows_to_match(staff, alice):
    APIToken.create_token(user=alice, name="reader", access_level="readonly")
    APIToken.create_token(user=alice, name="writer", access_level="staff")

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list") + "?access_level=staff", HTTP_HOST="localhost")
    levels = [t.access_level for t in resp.context["object_list"]]
    assert levels == ["staff"]


def test_combined_search_and_filter(staff, alice):
    APIToken.create_token(user=alice, name="mcp-claude")
    APIToken.create_token(user=alice, name="mcp-script")
    t, _ = APIToken.create_token(user=alice, name="mcp-old")
    t.revoke()

    c = Client()
    c.force_login(staff)
    resp = c.get(
        reverse("tokenmgr:tokens-list") + "?q=mcp&is_active=true",
        HTTP_HOST="localhost",
    )
    names = sorted(t.name for t in resp.context["object_list"])
    assert names == ["mcp-claude", "mcp-script"]


def test_htmx_request_returns_content_partial(staff, alice):
    """When HTMX hits the list with target=crud-list-content, the view
    returns just the inner table fragment — toolbar + page header are
    NOT re-rendered."""
    APIToken.create_token(user=alice, name="needle")
    c = Client()
    c.force_login(staff)
    resp = c.get(
        reverse("tokenmgr:tokens-list") + "?q=needle",
        HTTP_HOST="localhost",
        HTTP_HX_REQUEST="true",
        HTTP_HX_TARGET="crud-list-content",
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # Inner partial has the table but NOT the page header / stat cards.
    assert "needle" in body
    assert '<h1>API Tokens</h1>' not in body
    assert 'card-body" style="text-align: center' not in body


def test_initial_load_defaults_to_active_only(staff, alice):
    """Landing on /smallstack/tokens/ with no query string hides revoked
    tokens by default. The user can opt into seeing them via the dropdown."""
    APIToken.create_token(user=alice, name="alive")
    dead, _ = APIToken.create_token(user=alice, name="dead")
    dead.revoke()

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    names = sorted(t.name for t in resp.context["object_list"])
    assert names == ["alive"]


def test_explicit_all_filter_includes_revoked(staff, alice):
    """`?is_active=` (the "All" choice) bypasses the default and shows
    both active and revoked rows."""
    APIToken.create_token(user=alice, name="alive")
    dead, _ = APIToken.create_token(user=alice, name="dead")
    dead.revoke()

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list") + "?is_active=", HTTP_HOST="localhost")
    names = sorted(t.name for t in resp.context["object_list"])
    assert names == ["alive", "dead"]


def test_initial_load_dropdown_shows_yes_selected(staff, alice):
    """The Is Active dropdown reflects the default — `Yes` is selected
    so the URL state and the visible filter agree."""
    APIToken.create_token(user=alice, name="anything")
    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list"), HTTP_HOST="localhost")
    is_active_filter = next(
        f for f in resp.context["toolbar_filters"] if f["name"] == "is_active"
    )
    assert is_active_filter["current_value"] == "true"


def test_explicit_is_active_false_shows_revoked_only(staff, alice):
    """`?is_active=false` narrows to revoked tokens only — the default
    must not interfere with an explicit False choice."""
    APIToken.create_token(user=alice, name="alive")
    dead, _ = APIToken.create_token(user=alice, name="dead")
    dead.revoke()

    c = Client()
    c.force_login(staff)
    resp = c.get(reverse("tokenmgr:tokens-list") + "?is_active=false", HTTP_HOST="localhost")
    names = [t.name for t in resp.context["object_list"]]
    assert names == ["dead"]


def test_record_count_badge_reflects_filter(staff, alice):
    APIToken.create_token(user=alice, name="zz-needle-yy")
    APIToken.create_token(user=alice, name="other-1")
    APIToken.create_token(user=alice, name="other-2")

    c = Client()
    c.force_login(staff)
    # Use a long, unique string so the icontains match against `prefix`
    # (random characters) can't accidentally match too.
    resp = c.get(reverse("tokenmgr:tokens-list") + "?q=zz-needle-yy", HTTP_HOST="localhost")
    body = resp.content.decode()
    # Only the one named match → "1 record"
    assert "1 record" in body
