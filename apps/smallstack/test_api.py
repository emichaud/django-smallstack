"""Tests for the SmallStack REST API — pagination, serialization, and convenience features."""

from __future__ import annotations

import json
import math

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.heartbeat.models import Heartbeat

from .api import _build_filter_fields_spec, _resolve_expand_fields, _resolve_page, _serialize
from .models import APIToken

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_user(db) -> User:
    return User.objects.create_user(username="apistaff", email="api@example.com", password="testpass123", is_staff=True)


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
        hb = Heartbeat.objects.create(timestamp=timezone.now(), status="ok", response_time_ms=42)
        data = _serialize(hb, ["status"], extra_fields=["response_time_ms", "timestamp"])
        assert "id" in data
        assert data["status"] == "ok"
        assert data["response_time_ms"] == 42
        assert data["timestamp"] is not None  # ISO string

    def test_no_extra_fields(self, db):
        hb = Heartbeat.objects.create(timestamp=timezone.now(), status="ok", response_time_ms=42)
        data = _serialize(hb, ["status"])
        assert "response_time_ms" not in data

    def test_extra_fields_none(self, db):
        hb = Heartbeat.objects.create(timestamp=timezone.now(), status="ok", response_time_ms=42)
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
        page_size = len(client.get(url, {"page": "1"}, **auth_header).json()["results"])
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
        Heartbeat.objects.create(timestamp=timezone.now(), status="ok", response_time_ms=100)
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        assert data["page"] == 1
        assert data["total_pages"] == 1
        assert data["count"] == 1
        assert data["next"] is None
        assert data["previous"] is None


# ---------------------------------------------------------------------------
# Integration tests: page_size override
# ---------------------------------------------------------------------------


class TestPageSizeOverride:
    """Integration tests for ?page_size=N query param."""

    def test_page_size_increases_results(self, client, staff_user, heartbeats, auth_header):
        """?page_size=100 should return all 53 heartbeats in one page."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "100"}, **auth_header)
        data = response.json()
        assert data["count"] == 53
        assert len(data["results"]) == 53
        assert data["total_pages"] == 1
        assert data["next"] is None

    def test_page_size_reduces_results(self, client, staff_user, heartbeats, auth_header):
        """?page_size=5 should return only 5 results per page."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "5"}, **auth_header)
        data = response.json()
        assert len(data["results"]) == 5
        assert data["total_pages"] == 11  # ceil(53/5)

    def test_page_size_capped_at_1000(self, client, staff_user, heartbeats, auth_header):
        """?page_size=9999 is capped at 1000."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "9999"}, **auth_header)
        data = response.json()
        # With 53 items and effective page_size=1000, all fit on one page
        assert data["total_pages"] == 1
        assert len(data["results"]) == 53

    def test_page_size_zero_clamps_to_1(self, client, staff_user, heartbeats, auth_header):
        """?page_size=0 clamps to 1 (minimum)."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "0"}, **auth_header)
        data = response.json()
        assert len(data["results"]) == 1

    def test_page_size_invalid_ignored(self, client, staff_user, heartbeats, auth_header):
        """?page_size=abc falls back to default."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "abc"}, **auth_header)
        data = response.json()
        # Should use default page size, not crash
        assert response.status_code == 200
        assert data["count"] == 53

    def test_page_size_with_page_param(self, client, staff_user, heartbeats, auth_header):
        """?page_size and ?page compose correctly."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"page_size": "10", "page": "2"}, **auth_header)
        data = response.json()
        assert data["page"] == 2
        assert len(data["results"]) == 10
        assert data["total_pages"] == 6  # ceil(53/10)


# ---------------------------------------------------------------------------
# Unit tests: FK expansion in _serialize
# ---------------------------------------------------------------------------


class _FakeRelated:
    """Simulates a related object (has .pk and __str__)."""

    def __init__(self, pk: int, name: str):
        self.pk = pk
        self._name = name

    def __str__(self):
        return self._name


class _FakeObj:
    """Simulates a model instance for serialization tests."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestSerializeFKExpansion:
    """Unit tests for FK expansion in _serialize."""

    def test_fk_without_expand_returns_pk(self):
        related = _FakeRelated(pk=7, name="Electronics")
        obj = _FakeObj(pk=1, category=related, name="Widget")
        data = _serialize(obj, ["name", "category"])
        assert data["category"] == 7

    def test_fk_with_expand_returns_dict(self):
        related = _FakeRelated(pk=7, name="Electronics")
        obj = _FakeObj(pk=1, category=related, name="Widget")
        data = _serialize(obj, ["name", "category"], expand_fields={"category"})
        assert data["category"] == {"id": 7, "name": "Electronics"}

    def test_nullable_fk_with_expand_returns_null(self):
        obj = _FakeObj(pk=1, category=None, name="Widget")
        data = _serialize(obj, ["name", "category"], expand_fields={"category"})
        assert data["category"] is None

    def test_expand_non_fk_field_ignored(self):
        obj = _FakeObj(pk=1, name="Widget", is_active=True)
        data = _serialize(obj, ["name", "is_active"], expand_fields={"name"})
        # name is a string, not a FK — expand has no effect
        assert data["name"] == "Widget"

    def test_expand_field_not_in_fields_ignored(self):
        related = _FakeRelated(pk=7, name="Electronics")
        obj = _FakeObj(pk=1, category=related, name="Widget")
        # Expanding "other" which isn't in fields list — no error
        data = _serialize(obj, ["name", "category"], expand_fields={"other"})
        assert data["category"] == 7  # not expanded

    def test_expand_empty_set_behaves_like_none(self):
        related = _FakeRelated(pk=7, name="Electronics")
        obj = _FakeObj(pk=1, category=related)
        data = _serialize(obj, ["category"], expand_fields=set())
        assert data["category"] == 7

    def test_expand_with_extra_fields(self):
        related = _FakeRelated(pk=3, name="Alice")
        obj = _FakeObj(pk=1, name="Token", owner=related)
        data = _serialize(obj, ["name"], extra_fields=["owner"], expand_fields={"owner"})
        assert data["owner"] == {"id": 3, "name": "Alice"}

    def test_multiple_fk_expansion(self):
        cat = _FakeRelated(pk=7, name="Electronics")
        owner = _FakeRelated(pk=3, name="Alice")
        obj = _FakeObj(pk=1, category=cat, owner=owner, name="Widget")
        data = _serialize(obj, ["name", "category", "owner"], expand_fields={"category", "owner"})
        assert data["category"] == {"id": 7, "name": "Electronics"}
        assert data["owner"] == {"id": 3, "name": "Alice"}


# ---------------------------------------------------------------------------
# Unit tests: _resolve_expand_fields
# ---------------------------------------------------------------------------


class _FakeCrudConfig:
    """Minimal stub for crud_config in expand tests."""

    api_expand_fields = []


class TestResolveExpandFields:
    """Unit tests for _resolve_expand_fields."""

    def test_empty_default(self, rf):
        config = _FakeCrudConfig()
        request = rf.get("/api/test/")
        assert _resolve_expand_fields(request, config) == set()

    def test_api_expand_fields_only(self, rf):
        config = _FakeCrudConfig()
        config.api_expand_fields = ["category"]
        request = rf.get("/api/test/")
        assert _resolve_expand_fields(request, config) == {"category"}

    def test_query_param_only(self, rf):
        config = _FakeCrudConfig()
        request = rf.get("/api/test/", {"expand": "category,owner"})
        assert _resolve_expand_fields(request, config) == {"category", "owner"}

    def test_merge_config_and_param(self, rf):
        config = _FakeCrudConfig()
        config.api_expand_fields = ["category"]
        request = rf.get("/api/test/", {"expand": "owner"})
        assert _resolve_expand_fields(request, config) == {"category", "owner"}

    def test_whitespace_handling(self, rf):
        config = _FakeCrudConfig()
        request = rf.get("/api/test/", {"expand": " category , owner "})
        assert _resolve_expand_fields(request, config) == {"category", "owner"}

    def test_empty_expand_param(self, rf):
        config = _FakeCrudConfig()
        request = rf.get("/api/test/", {"expand": ""})
        assert _resolve_expand_fields(request, config) == set()

    def test_duplicate_in_both(self, rf):
        config = _FakeCrudConfig()
        config.api_expand_fields = ["category"]
        request = rf.get("/api/test/", {"expand": "category"})
        assert _resolve_expand_fields(request, config) == {"category"}


# ---------------------------------------------------------------------------
# Integration tests: FK expansion with real model
# ---------------------------------------------------------------------------


class TestFKExpansionIntegration:
    """Integration tests using APIToken which has a FK to User."""

    def test_apitoken_user_fk_not_expanded_by_default(self, staff_user, db):
        """APIToken.user should serialize as integer PK by default."""
        token, _ = APIToken.create_token(staff_user, name="Test")
        data = _serialize(token, ["name", "user"])
        assert data["user"] == staff_user.pk
        assert isinstance(data["user"], int)

    def test_apitoken_user_fk_expanded(self, staff_user, db):
        """Expanding user FK returns {id, name} dict."""
        token, _ = APIToken.create_token(staff_user, name="Test")
        data = _serialize(token, ["name", "user"], expand_fields={"user"})
        assert data["user"] == {"id": staff_user.pk, "name": str(staff_user)}


# ---------------------------------------------------------------------------
# Unit tests: _build_filter_fields_spec (smart date filtering)
# ---------------------------------------------------------------------------


class TestBuildFilterFieldsSpec:
    """Unit tests for auto-detecting date fields and expanding lookups."""

    def test_date_field_gets_range_lookups(self):
        """DateTimeField should get exact + gte/lte/gt/lt."""
        spec = _build_filter_fields_spec(Heartbeat, ["timestamp"])
        assert isinstance(spec, dict)
        assert spec["timestamp"] == ["exact", "gte", "lte", "gt", "lt"]

    def test_non_date_field_stays_exact(self):
        """CharField should stay exact-only."""
        spec = _build_filter_fields_spec(Heartbeat, ["status"])
        # No date fields → returns plain list
        assert spec == ["status"]

    def test_mixed_fields(self):
        """Mix of date and non-date fields returns dict with correct lookups."""
        spec = _build_filter_fields_spec(Heartbeat, ["status", "timestamp"])
        assert isinstance(spec, dict)
        assert spec["status"] == ["exact"]
        assert spec["timestamp"] == ["exact", "gte", "lte", "gt", "lt"]

    def test_unknown_field_gets_exact(self):
        """Non-existent field name defaults to exact."""
        spec = _build_filter_fields_spec(Heartbeat, ["nonexistent", "timestamp"])
        assert isinstance(spec, dict)
        assert spec["nonexistent"] == ["exact"]
        assert spec["timestamp"] == ["exact", "gte", "lte", "gt", "lt"]

    def test_empty_list_returns_empty(self):
        """Empty filter_fields returns empty list."""
        spec = _build_filter_fields_spec(Heartbeat, [])
        assert spec == []

    def test_apitoken_created_at(self):
        """APIToken.created_at (DateTimeField) gets range lookups."""
        spec = _build_filter_fields_spec(APIToken, ["is_active", "created_at"])
        assert isinstance(spec, dict)
        assert spec["is_active"] == ["exact"]
        assert spec["created_at"] == ["exact", "gte", "lte", "gt", "lt"]


# ---------------------------------------------------------------------------
# Integration tests: date range filtering via API
# ---------------------------------------------------------------------------


class TestDateFilteringIntegration:
    """Integration tests for date range filtering on the heartbeat API."""

    @pytest.fixture
    def dated_heartbeats(self, db):
        """Create heartbeats at specific times for filtering tests."""
        base = timezone.now()
        objs = []
        for i in range(10):
            objs.append(
                Heartbeat(
                    timestamp=base - timezone.timedelta(days=i),
                    status="ok",
                    response_time_ms=100 + i,
                )
            )
        return Heartbeat.objects.bulk_create(objs)

    def test_timestamp_gte_filter(self, client, staff_user, dated_heartbeats, auth_header):
        """?timestamp__gte= should filter to recent heartbeats only."""
        # Cutoff between day 4 and day 5 — should return days 0-4 (5 items)
        cutoff = (timezone.now() - timezone.timedelta(days=4, hours=12)).isoformat()
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"timestamp__gte": cutoff}, **auth_header)
        data = response.json()
        assert data["count"] == 5

    def test_timestamp_lte_filter(self, client, staff_user, dated_heartbeats, auth_header):
        """?timestamp__lte= should filter to older heartbeats."""
        # Cutoff between day 6 and day 7 — should return days 7-9 (3 items)
        cutoff = (timezone.now() - timezone.timedelta(days=6, hours=12)).isoformat()
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"timestamp__lte": cutoff}, **auth_header)
        data = response.json()
        assert data["count"] == 3

    def test_timestamp_range_filter(self, client, staff_user, dated_heartbeats, auth_header):
        """Combined gte + lte gives a date range."""
        now = timezone.now()
        # Between day 5.5 and day 1.5 — should capture days 2, 3, 4, 5 (4 items)
        gte = (now - timezone.timedelta(days=5, hours=12)).isoformat()
        lte = (now - timezone.timedelta(days=1, hours=12)).isoformat()
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"timestamp__gte": gte, "timestamp__lte": lte}, **auth_header)
        data = response.json()
        assert data["count"] == 4

    def test_exact_date_still_works(self, client, staff_user, db, auth_header):
        """Exact timestamp match should still work."""
        ts = timezone.now()
        Heartbeat.objects.create(timestamp=ts, status="ok", response_time_ms=100)
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"timestamp": ts.isoformat()}, **auth_header)
        data = response.json()
        assert data["count"] == 1


# ---------------------------------------------------------------------------
# Integration tests: Aggregation query params
# ---------------------------------------------------------------------------


class TestAggregationIntegration:
    """Integration tests for count_by, sum, avg, min, max on heartbeat API."""

    @pytest.fixture
    def mixed_heartbeats(self, db):
        """Create heartbeats with varied status and response times."""
        now = timezone.now()
        objs = (
            [
                Heartbeat(timestamp=now - timezone.timedelta(minutes=i), status="ok", response_time_ms=100)
                for i in range(5)
            ]
            + [
                Heartbeat(timestamp=now - timezone.timedelta(minutes=10 + i), status="fail", response_time_ms=500)
                for i in range(3)
            ]
            + [
                Heartbeat(timestamp=now - timezone.timedelta(minutes=20 + i), status="ok", response_time_ms=200)
                for i in range(2)
            ]
        )
        return Heartbeat.objects.bulk_create(objs)

    def test_count_by_status(self, client, staff_user, mixed_heartbeats, auth_header):
        """?count_by=status should return counts grouped by status."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"count_by": "status"}, **auth_header)
        data = response.json()
        assert "counts" in data
        assert data["counts"]["ok"] == 7
        assert data["counts"]["fail"] == 3
        # Normal response fields still present
        assert data["count"] == 10
        assert "results" in data

    def test_sum_response_time(self, client, staff_user, mixed_heartbeats, auth_header):
        """?sum=response_time_ms should return total."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"sum": "response_time_ms"}, **auth_header)
        data = response.json()
        # 5*100 + 3*500 + 2*200 = 500 + 1500 + 400 = 2400
        assert data["sum_response_time_ms"] == 2400

    def test_avg_response_time(self, client, staff_user, mixed_heartbeats, auth_header):
        """?avg=response_time_ms should return average."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"avg": "response_time_ms"}, **auth_header)
        data = response.json()
        # 2400 / 10 = 240.0
        assert data["avg_response_time_ms"] == 240.0

    def test_min_max_response_time(self, client, staff_user, mixed_heartbeats, auth_header):
        """?min= and ?max= should return extremes."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"min": "response_time_ms", "max": "response_time_ms"}, **auth_header)
        data = response.json()
        assert data["min_response_time_ms"] == 100
        assert data["max_response_time_ms"] == 500

    def test_multiple_aggregates(self, client, staff_user, mixed_heartbeats, auth_header):
        """Multiple aggregate ops in one request."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(
            url,
            {
                "sum": "response_time_ms",
                "avg": "response_time_ms",
                "min": "response_time_ms",
                "max": "response_time_ms",
            },
            **auth_header,
        )
        data = response.json()
        assert data["sum_response_time_ms"] == 2400
        assert data["avg_response_time_ms"] == 240.0
        assert data["min_response_time_ms"] == 100
        assert data["max_response_time_ms"] == 500

    def test_count_by_with_filter(self, client, staff_user, mixed_heartbeats, auth_header):
        """Aggregation composes with filters."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"status": "ok", "count_by": "status"}, **auth_header)
        data = response.json()
        assert data["count"] == 7
        assert data["counts"] == {"ok": 7}

    def test_sum_with_filter(self, client, staff_user, mixed_heartbeats, auth_header):
        """Sum composes with filters."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"status": "fail", "sum": "response_time_ms"}, **auth_header)
        data = response.json()
        assert data["sum_response_time_ms"] == 1500  # 3 * 500

    def test_count_by_invalid_field_returns_400(self, client, staff_user, db, auth_header):
        """count_by on a field not in filter_fields should return 400."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"count_by": "nonexistent"}, **auth_header)
        assert response.status_code == 400
        assert "not in filter_fields" in response.json()["errors"]["__all__"][0]

    def test_sum_invalid_field_returns_400(self, client, staff_user, db, auth_header):
        """sum on a field not in api_aggregate_fields should return 400."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"sum": "status"}, **auth_header)
        assert response.status_code == 400
        assert "not in api_aggregate_fields" in response.json()["errors"]["__all__"][0]

    def test_empty_queryset_aggregation(self, client, staff_user, db, auth_header):
        """Aggregation on empty queryset returns None/zero, not errors."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, {"sum": "response_time_ms", "count_by": "status"}, **auth_header)
        data = response.json()
        assert data["sum_response_time_ms"] is None
        assert data["counts"] == {}
        assert data["count"] == 0

    def test_no_aggregate_params_unchanged(self, client, staff_user, mixed_heartbeats, auth_header):
        """Without aggregate params, response is unchanged (backward compat)."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.get(url, **auth_header)
        data = response.json()
        assert "counts" not in data
        assert "sum_response_time_ms" not in data


# ---------------------------------------------------------------------------
# Integration tests: Auth token endpoint
# ---------------------------------------------------------------------------

AUTH_TOKEN_URL = "/api/auth/token/"


class TestAuthTokenEndpoint:
    """Integration tests for POST /api/auth/token/."""

    @pytest.fixture
    def regular_user(self, db):
        return User.objects.create_user(username="alice", email="alice@example.com", password="goodpass123")

    def test_valid_credentials_returns_token(self, client, regular_user):
        """Valid username + password returns 200 with token and user info."""
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "alice", "password": "goodpass123"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert len(data["token"]) > 20  # raw key is a long base64url string
        assert data["user"]["id"] == regular_user.pk
        assert data["user"]["username"] == "alice"

    def test_invalid_password_returns_401(self, client, regular_user):
        """Wrong password returns 401."""
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "alice", "password": "wrong"}),
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["errors"]["__all__"][0] == "Invalid credentials"

    def test_nonexistent_user_returns_401(self, client, db):
        """Non-existent username returns 401."""
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "nobody", "password": "whatever"}),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_inactive_user_returns_401(self, client, db):
        """Inactive user returns 401."""
        User.objects.create_user(username="inactive", password="pass123", is_active=False)
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "inactive", "password": "pass123"}),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_missing_fields_returns_400(self, client, db):
        """Missing username or password returns 400."""
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "alice"}),
            content_type="application/json",
        )
        assert response.status_code == 400

        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_invalid_json_returns_400(self, client, db):
        """Malformed JSON returns 400."""
        response = client.post(AUTH_TOKEN_URL, "not json", content_type="application/json")
        assert response.status_code == 400

    def test_get_method_not_allowed(self, client, db):
        """GET returns 405."""
        response = client.get(AUTH_TOKEN_URL)
        assert response.status_code == 405

    def test_returned_token_works_for_api_auth(self, client, staff_user):
        """Token returned by auth endpoint should work for Bearer auth on API."""
        # Get a token
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "apistaff", "password": "testpass123"}),
            content_type="application/json",
        )
        token = response.json()["token"]

        # Use it to access an API endpoint
        url = reverse(HEARTBEAT_API_LIST)
        api_response = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api_response.status_code == 200

    def test_staff_flag_in_response(self, client, staff_user):
        """is_staff should be reflected in the response."""
        response = client.post(
            AUTH_TOKEN_URL,
            json.dumps({"username": "apistaff", "password": "testpass123"}),
            content_type="application/json",
        )
        data = response.json()
        assert data["user"]["is_staff"] is True


# ---------------------------------------------------------------------------
# Integration tests: Schema endpoint
# ---------------------------------------------------------------------------

SCHEMA_URL = "/api/schema/"


class TestSchemaEndpoint:
    """Integration tests for GET /api/schema/."""

    def test_schema_returns_200_no_auth(self, client, db):
        """GET without auth returns 200."""
        response = client.get(SCHEMA_URL)
        assert response.status_code == 200

    def test_schema_contains_heartbeat(self, client, db):
        """Heartbeat should appear in the endpoints list."""
        response = client.get(SCHEMA_URL)
        data = response.json()
        models = [ep["model"] for ep in data["endpoints"]]
        assert "Heartbeat" in models

    def test_schema_endpoint_keys(self, client, db):
        """Each endpoint should have the expected keys."""
        response = client.get(SCHEMA_URL)
        data = response.json()
        expected_keys = {
            "url", "model", "methods", "fields", "list_fields",
            "detail_fields", "search_fields", "filter_fields",
            "expand_fields", "aggregate_fields", "extra_fields",
            "export_formats",
        }
        for ep in data["endpoints"]:
            assert set(ep.keys()) == expected_keys

    def test_schema_auth_section(self, client, db):
        """Auth dict should list all auth endpoints."""
        response = client.get(SCHEMA_URL)
        data = response.json()
        assert "auth" in data
        assert data["auth"]["login"] == "/api/auth/token/"
        assert data["auth"]["logout"] == "/api/auth/logout/"
        assert data["auth"]["register"] == "/api/auth/register/"
        assert data["auth"]["me"] == "/api/auth/me/"
        assert data["auth"]["password"] == "/api/auth/password/"
        assert data["auth"]["password_requirements"] == "/api/auth/password-requirements/"
        assert data["auth"]["users"] == "/api/auth/users/"
        assert data["auth"]["token_refresh"] == "/api/auth/token/refresh/"

    def test_schema_methods_match_actions(self, client, db):
        """Methods should reflect the Action enum for heartbeat."""
        response = client.get(SCHEMA_URL)
        data = response.json()
        heartbeat_ep = next(ep for ep in data["endpoints"] if ep["model"] == "Heartbeat")
        # Heartbeat has default actions (LIST, CREATE, DETAIL, UPDATE, DELETE)
        assert "GET" in heartbeat_ep["methods"]
        assert "POST" in heartbeat_ep["methods"]

    def test_schema_post_405(self, client, db):
        """POST to schema endpoint returns 405."""
        response = client.post(SCHEMA_URL)
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Integration tests: OPTIONS field metadata
# ---------------------------------------------------------------------------


class TestOptionsEndpoint:
    """Integration tests for OPTIONS on CRUDView API endpoints."""

    def test_options_no_auth_required(self, client, db):
        """OPTIONS returns 200 without auth."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.options(url)
        assert response.status_code == 200

    def test_options_has_fields(self, client, db):
        """Response contains a fields dict."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.options(url)
        data = response.json()
        assert "fields" in data
        assert isinstance(data["fields"], dict)

    def test_options_field_types(self, client, db):
        """Correct types for known heartbeat fields."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.options(url)
        data = response.json()
        fields = data["fields"]
        assert fields["timestamp"]["type"] == "datetime"
        assert fields["status"]["type"] == "choice"
        assert fields["response_time_ms"]["type"] == "integer"
        assert fields["note"]["type"] == "string"

    def test_options_extra_fields_readonly(self, client, db):
        """api_extra_fields should have read_only: true."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.options(url)
        data = response.json()
        # Heartbeat doesn't have api_extra_fields by default,
        # but check that form fields don't have read_only
        for name in ("timestamp", "status", "response_time_ms"):
            assert "read_only" not in data["fields"][name]

    def test_options_includes_methods(self, client, db):
        """Response should have a methods list."""
        url = reverse(HEARTBEAT_API_LIST)
        response = client.options(url)
        data = response.json()
        assert "methods" in data
        assert isinstance(data["methods"], list)
        assert "GET" in data["methods"]

    def test_options_on_detail_endpoint(self, client, db):
        """OPTIONS on the detail endpoint also works without auth."""
        # Use the detail URL pattern name
        url = reverse("explorer-monitoring-heartbeat-api-detail", kwargs={"pk": 1})
        response = client.options(url)
        assert response.status_code == 200
        data = response.json()
        assert "fields" in data
        assert "methods" in data


# ---------------------------------------------------------------------------
# Fixtures for user management and token refresh tests
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_level_token(staff_user) -> tuple[APIToken, str]:
    """Create an auth-level manual token."""
    return APIToken.create_token(staff_user, name="Auth Token", access_level="auth")


@pytest.fixture
def auth_level_header(auth_level_token) -> dict[str, str]:
    """Authorization header for auth-level token."""
    _, raw_key = auth_level_token
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


@pytest.fixture
def sample_users(db) -> list:
    """Create 15 users for list/search pagination testing."""
    users = []
    for i in range(15):
        users.append(
            User.objects.create_user(
                username=f"testuser{i:02d}",
                email=f"testuser{i:02d}@example.com",
                password="testpass123",
                first_name=f"First{i:02d}",
                last_name=f"Last{i:02d}",
            )
        )
    return users


@pytest.fixture
def login_token_and_header(db):
    """Create a user with a login token, return (user, token, raw_key, header)."""
    from datetime import timedelta

    user = User.objects.create_user(username="loginuser", password="testpass123", email="login@example.com")
    raw_key, prefix, hashed = APIToken._generate_raw_key()
    token = APIToken.objects.create(
        user=user, name="Login token", prefix=prefix, hashed_key=hashed,
        token_type="login", access_level="", expires_at=timezone.now() + timedelta(hours=24),
    )
    header = {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}
    return user, token, raw_key, header


# ---------------------------------------------------------------------------
# Integration tests: User list endpoint
# ---------------------------------------------------------------------------

USERS_URL = "/api/auth/users/"


class TestUserListEndpoint:
    """Integration tests for GET /api/auth/users/."""

    def test_list_requires_auth_level_token(self, client, staff_user, auth_header, db):
        """Staff-level token returns 403."""
        response = client.get(USERS_URL, **auth_header)
        assert response.status_code == 403

    def test_list_returns_paginated_users(self, client, staff_user, sample_users, auth_level_header):
        """Returns paginated response with correct shape."""
        response = client.get(USERS_URL, **auth_level_header)
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "page" in data
        assert "total_pages" in data
        assert "results" in data
        assert "next" in data
        assert "previous" in data

    def test_list_extended_user_fields(self, client, staff_user, sample_users, auth_level_header):
        """Extended fields present in response."""
        response = client.get(USERS_URL, **auth_level_header)
        data = response.json()
        user_data = data["results"][0]
        assert "first_name" in user_data
        assert "last_name" in user_data
        assert "is_active" in user_data
        assert "date_joined" in user_data

    def test_list_search_by_username(self, client, staff_user, sample_users, auth_level_header):
        """?q= filters by username."""
        response = client.get(USERS_URL, {"q": "testuser05"}, **auth_level_header)
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["username"] == "testuser05"

    def test_list_search_by_email(self, client, staff_user, sample_users, auth_level_header):
        """?q= filters by email."""
        response = client.get(USERS_URL, {"q": "testuser03@"}, **auth_level_header)
        data = response.json()
        assert data["count"] == 1
        assert data["results"][0]["email"] == "testuser03@example.com"

    def test_list_search_no_match(self, client, staff_user, sample_users, auth_level_header):
        """No match returns empty results."""
        response = client.get(USERS_URL, {"q": "nonexistent_xyz"}, **auth_level_header)
        data = response.json()
        assert data["count"] == 0
        assert data["results"] == []

    def test_list_pagination(self, client, staff_user, sample_users, auth_level_header):
        """page_size and page params work."""
        response = client.get(USERS_URL, {"page_size": "5", "page": "2"}, **auth_level_header)
        data = response.json()
        assert data["page"] == 2
        assert len(data["results"]) == 5

    def test_list_unauthenticated_returns_401(self, client, db):
        """No auth returns 401."""
        response = client.get(USERS_URL)
        assert response.status_code == 401

    def test_list_post_method_not_allowed(self, client, staff_user, auth_level_header, db):
        """POST returns 405."""
        response = client.post(USERS_URL, **auth_level_header)
        assert response.status_code == 405


# ---------------------------------------------------------------------------
# Integration tests: User detail endpoint
# ---------------------------------------------------------------------------


class TestUserDetailEndpoint:
    """Integration tests for GET /api/auth/users/<id>/."""

    def test_detail_returns_user(self, client, staff_user, auth_level_header, sample_users):
        """GET returns extended user data."""
        target = sample_users[0]
        response = client.get(f"{USERS_URL}{target.pk}/", **auth_level_header)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == target.username
        assert "first_name" in data
        assert "date_joined" in data

    def test_detail_not_found(self, client, staff_user, auth_level_header, db):
        """Non-existent user returns 404."""
        response = client.get(f"{USERS_URL}99999/", **auth_level_header)
        assert response.status_code == 404

    def test_detail_requires_auth_level_token(self, client, staff_user, auth_header, sample_users):
        """Staff token returns 403."""
        target = sample_users[0]
        response = client.get(f"{USERS_URL}{target.pk}/", **auth_header)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests: User update endpoint
# ---------------------------------------------------------------------------


class TestUserUpdateEndpoint:
    """Integration tests for PATCH /api/auth/users/<id>/."""

    def test_update_email(self, client, staff_user, auth_level_header, sample_users):
        """PATCH updates email."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"email": "new@example.com"}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 200
        assert response.json()["email"] == "new@example.com"

    def test_update_multiple_fields(self, client, staff_user, auth_level_header, sample_users):
        """Updates first_name, last_name, is_staff."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"first_name": "New", "last_name": "Name", "is_staff": True}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "New"
        assert data["last_name"] == "Name"
        assert data["is_staff"] is True

    def test_update_disallowed_field_username(self, client, staff_user, auth_level_header, sample_users):
        """username is not allowed in PATCH."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"username": "hacked"}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 400
        assert "username" in response.json()["errors"]

    def test_update_disallowed_field_password(self, client, staff_user, auth_level_header, sample_users):
        """password is not allowed in PATCH."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"password": "hacked"}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 400
        assert "password" in response.json()["errors"]

    def test_update_not_found(self, client, staff_user, auth_level_header, db):
        """Non-existent user returns 404."""
        response = client.patch(
            f"{USERS_URL}99999/",
            json.dumps({"email": "x@x.com"}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 404

    def test_update_requires_auth_level_token(self, client, staff_user, auth_header, sample_users):
        """Staff token returns 403."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"email": "x@x.com"}),
            content_type="application/json",
            **auth_header,
        )
        assert response.status_code == 403

    def test_update_invalid_json(self, client, staff_user, auth_level_header, sample_users):
        """Invalid JSON returns 400."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            "not json",
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 400

    def test_update_is_active_toggle(self, client, staff_user, auth_level_header, sample_users):
        """Deactivate user via is_active: false."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({"is_active": False}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_update_empty_body(self, client, staff_user, auth_level_header, sample_users):
        """Empty body returns 200 with unchanged user."""
        target = sample_users[0]
        response = client.patch(
            f"{USERS_URL}{target.pk}/",
            json.dumps({}),
            content_type="application/json",
            **auth_level_header,
        )
        assert response.status_code == 200
        assert response.json()["username"] == target.username


# ---------------------------------------------------------------------------
# Integration tests: Token refresh endpoint
# ---------------------------------------------------------------------------

TOKEN_REFRESH_URL = "/api/auth/token/refresh/"


class TestTokenRefreshEndpoint:
    """Integration tests for POST /api/auth/token/refresh/."""

    def test_refresh_returns_new_token(self, client, login_token_and_header):
        """Refresh returns a new token."""
        user, token, old_key, header = login_token_and_header
        response = client.post(TOKEN_REFRESH_URL, **header)
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["token"] != old_key
        assert data["user"]["id"] == user.pk
        assert "expires_at" in data

    def test_refresh_old_token_stops_working(self, client, login_token_and_header):
        """Old key returns 401 after refresh."""
        user, token, old_key, header = login_token_and_header
        client.post(TOKEN_REFRESH_URL, **header)
        # Old key should fail
        response = client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {old_key}")
        assert response.status_code == 401

    def test_refresh_new_token_works(self, client, login_token_and_header):
        """New key authenticates successfully."""
        user, token, old_key, header = login_token_and_header
        refresh_resp = client.post(TOKEN_REFRESH_URL, **header)
        new_key = refresh_resp.json()["token"]
        response = client.get("/api/auth/me/", HTTP_AUTHORIZATION=f"Bearer {new_key}")
        assert response.status_code == 200
        assert response.json()["id"] == user.pk

    def test_refresh_extends_expiry(self, client, login_token_and_header):
        """expires_at should be in the future."""
        from datetime import datetime

        user, token, old_key, header = login_token_and_header
        response = client.post(TOKEN_REFRESH_URL, **header)
        data = response.json()
        expires = datetime.fromisoformat(data["expires_at"])
        assert expires > timezone.now()

    def test_refresh_custom_expires_hours(self, client, login_token_and_header):
        """Custom expires_hours is respected."""
        from datetime import datetime, timedelta

        user, token, old_key, header = login_token_and_header
        response = client.post(
            TOKEN_REFRESH_URL,
            json.dumps({"expires_hours": 48}),
            content_type="application/json",
            **header,
        )
        data = response.json()
        expires = datetime.fromisoformat(data["expires_at"])
        # Should be roughly 48 hours from now (within 5 min tolerance)
        expected = timezone.now() + timedelta(hours=48)
        assert abs((expires - expected).total_seconds()) < 300

    def test_refresh_expires_hours_capped(self, client, login_token_and_header, settings):
        """expires_hours capped at SMALLSTACK_LOGIN_TOKEN_MAX_HOURS."""
        from datetime import datetime, timedelta

        settings.SMALLSTACK_LOGIN_TOKEN_MAX_HOURS = 72
        user, token, old_key, header = login_token_and_header
        response = client.post(
            TOKEN_REFRESH_URL,
            json.dumps({"expires_hours": 9999}),
            content_type="application/json",
            **header,
        )
        data = response.json()
        expires = datetime.fromisoformat(data["expires_at"])
        expected = timezone.now() + timedelta(hours=72)
        assert abs((expires - expected).total_seconds()) < 300

    def test_refresh_manual_token_rejected(self, client, staff_user, auth_header, db):
        """Manual token returns 403."""
        response = client.post(TOKEN_REFRESH_URL, **auth_header)
        assert response.status_code == 403

    def test_refresh_expired_token_returns_401(self, client, db):
        """Expired login token returns 401."""
        from datetime import timedelta

        user = User.objects.create_user(username="expired", password="pass123")
        raw_key, prefix, hashed = APIToken._generate_raw_key()
        APIToken.objects.create(
            user=user, name="Expired", prefix=prefix, hashed_key=hashed,
            token_type="login", access_level="",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        response = client.post(TOKEN_REFRESH_URL, HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        assert response.status_code == 401

    def test_refresh_unauthenticated_returns_401(self, client, db):
        """No auth returns 401."""
        response = client.post(TOKEN_REFRESH_URL)
        assert response.status_code == 401

    def test_refresh_get_method_not_allowed(self, client, db):
        """GET returns 405."""
        response = client.get(TOKEN_REFRESH_URL)
        assert response.status_code == 405

    def test_refresh_empty_body_uses_defaults(self, client, login_token_and_header):
        """Empty body uses default expiry."""
        user, token, old_key, header = login_token_and_header
        response = client.post(TOKEN_REFRESH_URL, **header)
        assert response.status_code == 200
        assert "token" in response.json()
