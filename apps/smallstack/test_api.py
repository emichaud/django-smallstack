"""Tests for the SmallStack REST API — pagination, serialization, and convenience features."""

from __future__ import annotations

import json
import math

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.heartbeat.models import Heartbeat

from .api import _resolve_page, _serialize
from .models import APIToken

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_user(db) -> User:
    return User.objects.create_user(
        username="apistaff", email="api@example.com", password="testpass123", is_staff=True
    )


@pytest.fixture
def api_token(staff_user) -> tuple[APIToken, str]:
    """Create an API token, return (token_instance, raw_key)."""
    return APIToken.create_token(staff_user, name="Test Token")


@pytest.fixture
def auth_header(api_token) -> dict[str, str]:
    """Authorization header dict for use with test client."""
    _, raw_key = api_token
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


@pytest.fixture
def heartbeats(db) -> list[Heartbeat]:
    """Create 53 heartbeat records for pagination testing."""
    now = timezone.now()
    objs = [
        Heartbeat(
            timestamp=now - timezone.timedelta(minutes=i),
            status="ok",
            response_time_ms=100 + i,
        )
        for i in range(53)
    ]
    return Heartbeat.objects.bulk_create(objs)


# ---------------------------------------------------------------------------
# Unit tests: _resolve_page
# ---------------------------------------------------------------------------


class TestResolvePage:
    """Unit tests for the _resolve_page helper."""

    def test_numeric_page(self):
        assert _resolve_page("3", total_pages=10) == 3

    def test_numeric_page_one(self):
        assert _resolve_page("1", total_pages=10) == 1

    def test_numeric_last_page(self):
        assert _resolve_page("10", total_pages=10) == 10

    def test_first_alias(self):
        assert _resolve_page("first", total_pages=10) == 1

    def test_first_alias_case_insensitive(self):
        assert _resolve_page("First", total_pages=10) == 1
        assert _resolve_page("FIRST", total_pages=10) == 1

    def test_last_alias(self):
        assert _resolve_page("last", total_pages=10) == 10

    def test_last_alias_case_insensitive(self):
        assert _resolve_page("Last", total_pages=10) == 10

    def test_last_with_single_page(self):
        assert _resolve_page("last", total_pages=1) == 1

    def test_next_alias(self):
        assert _resolve_page("next", total_pages=10, current=3) == 4

    def test_next_alias_clamps_at_end(self):
        assert _resolve_page("next", total_pages=10, current=10) == 10

    def test_next_without_current_defaults_to_page_2(self):
        assert _resolve_page("next", total_pages=10) == 2

    def test_next_without_current_single_page(self):
        assert _resolve_page("next", total_pages=1) == 1

    def test_prev_alias(self):
        assert _resolve_page("prev", total_pages=10, current=5) == 4

    def test_previous_alias(self):
        assert _resolve_page("previous", total_pages=10, current=5) == 4

    def test_prev_clamps_at_start(self):
        assert _resolve_page("prev", total_pages=10, current=1) == 1

    def test_prev_without_current_stays_at_1(self):
        assert _resolve_page("prev", total_pages=10) == 1

    def test_numeric_below_range_clamps_to_1(self):
        assert _resolve_page("0", total_pages=10) == 1
        assert _resolve_page("-5", total_pages=10) == 1

    def test_numeric_above_range_clamps_to_last(self):
        assert _resolve_page("99", total_pages=10) == 10

    def test_invalid_string_returns_1(self):
        assert _resolve_page("abc", total_pages=10) == 1

    def test_empty_string_returns_1(self):
        assert _resolve_page("", total_pages=10) == 1

    def test_whitespace_stripped(self):
        assert _resolve_page("  last  ", total_pages=5) == 5
        assert _resolve_page("  3  ", total_pages=5) == 3

    def test_total_pages_zero(self):
        """When total_pages=0 (edge case), _resolve_page should not crash.

        In practice _api_list uses max(1, ...) so total_pages is always >= 1.
        """
        # numeric clamps: max(1, min(1, 0)) = 1
        assert _resolve_page("1", total_pages=0) == 1
        # last returns total_pages directly
        assert _resolve_page("last", total_pages=0) == 0
        # first is always 1
        assert _resolve_page("first", total_pages=0) == 1


# ---------------------------------------------------------------------------
# Unit tests: _serialize with extra_fields
# ---------------------------------------------------------------------------


class TestSerializeExtraFields:
    """Test that api_extra_fields are included in serialization."""

    def test_extra_fields_appended(self, db):
        hb = Heartbeat.objects.create(
            timestamp=timezone.now(), status="ok", response_time_ms=42
        )
        data = _serialize(hb, ["status"], extra_fields=["response_time_ms", "timestamp"])
        assert "id" in data
        assert data["status"] == "ok"
        assert data["response_time_ms"] == 42
        assert data["timestamp"] is not None  # ISO string

    def test_no_extra_fields(self, db):
        hb = Heartbeat.objects.create(
            timestamp=timezone.now(), status="ok", response_time_ms=42
        )
        data = _serialize(hb, ["status"])
        assert "response_time_ms" not in data

    def test_extra_fields_none(self, db):
        hb = Heartbeat.objects.create(
            timestamp=timezone.now(), status="ok", response_time_ms=42
        )
        data = _serialize(hb, ["status"], extra_fields=None)
        assert "response_time_ms" not in data


# ---------------------------------------------------------------------------
# Integration tests: API pagination endpoints
# ---------------------------------------------------------------------------

# Heartbeat API list URL name from explorer registration
HEARTBEAT_API_LIST = "explorer-monitoring-heartbeat-api-list"


class TestAPIPaginationIntegration:
    """Integration tests for pagination convenience params via the real API."""

    def test_default_page_is_1(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        assert data["page"] == 1
        assert data["count"] == 53

    def test_total_pages_in_response(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        # Default page size from explorer is 10 or 25; heartbeats has 53 items
        expected_pages = math.ceil(53 / data["total_pages"] * data["total_pages"])
        assert data["total_pages"] == math.ceil(53 / (len(data["results"]) or 1))

    def test_page_first(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "first"}, **auth_header)
        data = response.json()
        assert data["page"] == 1
        assert data["previous"] is None

    def test_page_last(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "last"}, **auth_header)
        data = response.json()
        assert data["page"] == data["total_pages"]
        assert data["next"] is None
        assert len(data["results"]) > 0

    def test_page_last_returns_remainder(self, client, staff_user, heartbeats, auth_header):
        """Last page should have the remaining items, not a full page (unless exact multiple)."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "last"}, **auth_header)
        data = response.json()
        page_size = len(
            client.get(url, {"page": "1"}, **auth_header).json()["results"]
        )
        remainder = 53 % page_size
        if remainder == 0:
            assert len(data["results"]) == page_size
        else:
            assert len(data["results"]) == remainder

    def test_page_numeric(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "2"}, **auth_header)
        data = response.json()
        assert data["page"] == 2
        assert data["previous"] is not None
        assert "page=1" in data["previous"]

    def test_page_out_of_range_clamps(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "9999"}, **auth_header)
        data = response.json()
        assert data["page"] == data["total_pages"]
        assert data["next"] is None

    def test_page_zero_clamps_to_1(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "0"}, **auth_header)
        data = response.json()
        assert data["page"] == 1

    def test_page_negative_clamps_to_1(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "-1"}, **auth_header)
        data = response.json()
        assert data["page"] == 1

    def test_page_invalid_string_returns_page_1(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "xyz"}, **auth_header)
        data = response.json()
        assert data["page"] == 1

    def test_next_previous_links_consistent(self, client, staff_user, heartbeats, auth_header):
        """Verify that following next/previous links produces correct page numbers."""
        url = reverse(HEARTBEAT_API_LIST)

        # Get page 1
        r1 = client.get(url, {"page": "1"}, **auth_header).json()
        assert r1["page"] == 1
        assert r1["previous"] is None
        assert r1["next"] is not None

        # Follow next link to page 2
        r2 = client.get(r1["next"], **auth_header).json()
        assert r2["page"] == 2
        assert r2["previous"] is not None

    def test_empty_queryset_returns_page_1(self, client, staff_user, db, auth_header):
        """With no data, should return page 1, total_pages 1, empty results."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        assert data["page"] == 1
        assert data["total_pages"] == 1
        assert data["count"] == 0
        assert data["results"] == []
        assert data["next"] is None
        assert data["previous"] is None

    def test_page_first_case_insensitive(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "FIRST"}, **auth_header)
        assert response.json()["page"] == 1

    def test_page_last_case_insensitive(self, client, staff_user, heartbeats, auth_header):
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page": "LAST"}, **auth_header)
        data = response.json()
        assert data["page"] == data["total_pages"]

    def test_single_page_dataset(self, client, staff_user, db, auth_header):
        """With fewer items than page_size, everything is on page 1."""
        Heartbeat.objects.create(
            timestamp=timezone.now(), status="ok", response_time_ms=100
        )
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        assert data["page"] == 1
        assert data["total_pages"] == 1
        assert data["count"] == 1
        assert data["next"] is None
        assert data["previous"] is None
