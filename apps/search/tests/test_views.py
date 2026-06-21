"""HTML search page + omnibar JSON endpoint."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_client():
    User = get_user_model()
    user = User.objects.create_user(
        username="search-staff", password="p", email="s@example.com", is_staff=True
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def non_staff_client():
    """A signed-in, non-staff user — should be admitted by the page (v0.11.8)
    even though they previously got 403 under StaffRequiredMixin."""
    User = get_user_model()
    user = User.objects.create_user(
        username="search-regular", password="p", email="r@example.com", is_staff=False
    )
    client = Client()
    client.force_login(user)
    return client


def test_search_page_anon_redirected(client):
    resp = client.get(reverse("search:page"))
    assert resp.status_code in (302, 401, 403)


def test_search_page_staff_renders(staff_client):
    resp = staff_client.get(reverse("search:page"))
    assert resp.status_code == 200
    assert b"Search" in resp.content


def test_search_page_non_staff_renders(non_staff_client):
    """Audit round-2 finding §4.2: non-staff authenticated users used to
    get a bare 403 here, contradicting the SearchAccess.AUTHENTICATED tier
    promised in docs/skills/search.md. The page is now LoginRequiredMixin —
    the registry enforces per-view access, not the page mixin."""
    resp = non_staff_client.get(reverse("search:page"))
    assert resp.status_code == 200
    assert b"Search" in resp.content


def test_search_page_non_staff_sees_no_staff_only_sources(non_staff_client):
    """Non-staff get the page but the indexed_sources panel is filtered:
    the bundled STAFF-tier sources (User, APIToken) are hidden.

    Assertion is "the specific STAFF-tier sources we ship by default are
    hidden" rather than "no model sources visible at all" — round-4 audit
    A1 — so the test survives downstream projects that register their own
    AUTH-tier CRUDViews per ``building-a-user-facing-site.md``.
    """
    resp = non_staff_client.get(reverse("search:page"))
    sources = resp.context["indexed_sources"]
    model_labels = {s["model_label"] for s in sources if s["kind"] == "model"}
    # The default STAFF-tier opt-ins ship as User + APIToken; both must
    # be hidden from a non-staff caller.
    assert "accounts.User" not in model_labels
    assert "smallstack.APIToken" not in model_labels


def test_search_page_with_query_shows_results_or_no_match(staff_client):
    resp = staff_client.get(reverse("search:page") + "?q=nothing-matches-this-99zz")
    assert resp.status_code == 200
    # Either a "no matches" message or zero result groups
    assert b"results" in resp.content.lower() or b"no matches" in resp.content.lower()


def test_search_page_empty_query_shows_help(staff_client):
    """No query → render the query-syntax help table."""
    resp = staff_client.get(reverse("search:page"))
    body = resp.content.decode()
    # The redesigned label splits "Query" and "syntax" on two lines via
    # a <br>, so match the two halves separately. The syntax-table
    # examples must still be present.
    assert "Query" in body and "syntax" in body
    assert "refund*" in body


def test_omnibar_json_anon_blocked(client):
    resp = client.get(reverse("search:omnibar") + "?q=test")
    assert resp.status_code in (302, 401, 403)


def test_omnibar_json_returns_results_shape(staff_client):
    resp = staff_client.get(reverse("search:omnibar") + "?q=test")
    assert resp.status_code == 200
    data = resp.json()
    assert "query" in data and "results" in data
    assert isinstance(data["results"], list)


def test_omnibar_empty_query_returns_empty(staff_client):
    resp = staff_client.get(reverse("search:omnibar"))
    assert resp.status_code == 200
    assert resp.json()["results"] == []
