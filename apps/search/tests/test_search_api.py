"""Tests for SearchAPI class."""


import pytest

from apps.search.api import SearchAPI, get_search_api
from apps.search.registry import register, unregister


class MockModel:
    """Mock Django model for testing."""
    _meta = type('Meta', (), {
        'app_label': 'test',
        'verbose_name': 'Mock',
        'verbose_name_plural': 'Mocks',
    })()

    class objects:
        @staticmethod
        def filter(**kwargs):
            class MockQuerySet:
                def __init__(self):
                    self.filtered = True
                def values_list(self, *args, **kwargs):
                    return []
            return MockQuerySet()

        @staticmethod
        def all():
            return []

    def __init__(self, pk=1, title="Test"):
        self.pk = pk
        self.title = title


class SimpleCRUDView:
    """CRUDView without SearchBuilder."""
    model = MockModel
    search_fields = ["title"]
    enable_search = True


class TestSearchAPI:
    """Test SearchAPI introspection and query methods."""

    def test_get_search_api_singleton(self):
        """get_search_api() returns same instance."""
        api1 = get_search_api()
        api2 = get_search_api()
        assert api1 is api2

    def test_api_get_config_nonexistent(self):
        """get_config for nonexistent model returns empty dict."""
        api = SearchAPI()
        config = api.get_config("nonexistent.Model")
        assert config == {}

    def test_api_get_config_registered(self):
        """get_config returns config for registered view."""
        register(SimpleCRUDView)
        try:
            api = SearchAPI()
            config = api.get_config("test.MockModel")
            assert config["model_label"] == "test.MockModel"
            assert "title" in config["fields"]
        finally:
            unregister("test.MockModel")

    def test_api_list_variants(self):
        """list_variants returns all registered view configs."""
        register(SimpleCRUDView)
        try:
            api = SearchAPI()
            configs = api.list_variants()
            assert any(c["model_label"] == "test.MockModel" for c in configs)
        finally:
            unregister("test.MockModel")

    def test_api_search_empty_query(self):
        """search with empty query returns empty list."""
        api = SearchAPI()
        results = api.search("test.MockModel", "")
        assert results == []

    def test_api_search_nonexistent_model(self):
        """search for nonexistent model raises ValueError."""
        api = SearchAPI()
        with pytest.raises(ValueError):
            api.search("nonexistent.Model", "test query")

    def test_api_get_output_schema(self):
        """get_output_schema returns proper structure."""
        register(SimpleCRUDView)
        try:
            api = SearchAPI()
            schema = api.get_output_schema("test.MockModel")
            assert schema["type"] == "object"
            assert "display" in schema["properties"]
            assert "object_id" in schema["properties"]
        finally:
            unregister("test.MockModel")

    def test_api_get_output_schema_nonexistent(self):
        """get_output_schema for nonexistent model raises ValueError."""
        api = SearchAPI()
        with pytest.raises(ValueError):
            api.get_output_schema("nonexistent.Model")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
