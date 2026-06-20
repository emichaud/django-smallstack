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


def test_search_page_anon_redirected(client):
    resp = client.get(reverse("search:page"))
    assert resp.status_code in (302, 401, 403)


def test_search_page_staff_renders(staff_client):
    resp = staff_client.get(reverse("search:page"))
    assert resp.status_code == 200
    assert b"Search" in resp.content


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
