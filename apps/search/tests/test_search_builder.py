"""Unit tests for SearchBuilder protocol detection and introspection."""

from typing import Any

import pytest
from django.db.models import QuerySet

from apps.search.backends.base import SearchHit
from apps.search.registry import (
    _has_search_builder,
    get_search_config,
    list_search_configs,
    register,
    unregister,
)


class MockModel:
    """Mock Django model for testing."""
    _meta = type('Meta', (), {
        'app_label': 'test',
        'verbose_name': 'Mock',
        'verbose_name_plural': 'Mocks',
    })()

    def __init__(self, pk=1, title="Test"):
        self.pk = pk
        self.title = title


class SimpleCRUDView:
    """CRUDView without SearchBuilder."""
    model = MockModel
    search_fields = ["title"]
    enable_search = True


class SearchBuilderCRUDView:
    """CRUDView with full SearchBuilder implementation."""
    model = MockModel
    search_fields = ["title"]
    enable_search = True

    def get_search_variants(self) -> dict[str, str]:
        return {
            "default": "Full output",
            "summary": "Title only",
        }

    def transform_hit(self, obj: Any, variant: str = "default") -> dict[str, Any]:
        if variant == "summary":
            return {"display": obj.title}
        return {"display": obj.title, "subtitle": "Full data"}

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        return qs

    def get_ranking_weights(self) -> dict[str, int]:
        return {"title": 2}


class TestSearchBuilderDetection:
    """Test _has_search_builder() function."""

    def test_view_without_builder(self):
        """Non-builder views return False."""
        assert not _has_search_builder(SimpleCRUDView)

    def test_view_with_builder(self):
        """Views with SearchBuilder methods return True."""
        assert _has_search_builder(SearchBuilderCRUDView)

    def test_partial_builder(self):
        """Views with some (but not all) SearchBuilder methods return True."""
        class PartialView:
            def get_search_variants(self):
                return {"default": "Test"}

        assert _has_search_builder(PartialView)


class TestSearchConfigRetrieval:
    """Test get_search_config() and list_search_configs()."""

    def test_get_config_nonexistent_model(self):
        """Nonexistent models return empty dict."""
        config = get_search_config("nonexistent.Model")
        assert config == {}

    def test_get_config_basic(self):
        """Basic config retrieval for registered view."""
        register(SimpleCRUDView)
        try:
            config = get_search_config("test.MockModel")
            assert config["model_label"] == "test.MockModel"
            assert "title" in config["fields"]
            assert config["has_search_builder"] is False
        finally:
            unregister("test.MockModel")

    def test_get_config_with_variants(self):
        """Views with SearchBuilder include variants in config."""
        register(SearchBuilderCRUDView)
        try:
            config = get_search_config("test.MockModel")

            assert config["has_search_builder"] is True
            assert "default" in config["variants"]
            assert "summary" in config["variants"]
        finally:
            unregister("test.MockModel")

    def test_list_all_configs(self):
        """list_search_configs returns all registered views."""
        register(SimpleCRUDView)
        try:
            configs = list_search_configs()
            assert any(c["model_label"] == "test.MockModel" for c in configs)
        finally:
            unregister("test.MockModel")


class TestSearchHitExtra:
    """Test SearchHit extra field for variant data."""

    def test_searchhit_extra_field_exists(self):
        """SearchHit has extra field for variant data."""
        hit = SearchHit(
            model_label="test.MockModel",
            model_verbose="Mock",
            object_id=1,
            display="Test",
            extra={"custom_field": "value"}
        )
        assert hit.extra == {"custom_field": "value"}

    def test_searchhit_as_dict_includes_extra(self):
        """as_dict() includes extra fields in output."""
        hit = SearchHit(
            model_label="test.MockModel",
            model_verbose="Mock",
            object_id=1,
            display="Test",
            extra={"custom_field": "value"}
        )
        d = hit.as_dict()
        assert d["custom_field"] == "value"

    def test_searchhit_as_dict_without_extra(self):
        """as_dict() works fine without extra fields."""
        hit = SearchHit(
            model_label="test.MockModel",
            model_verbose="Mock",
            object_id=1,
            display="Test"
        )
        d = hit.as_dict()
        assert "custom_field" not in d
        assert d["display"] == "Test"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
