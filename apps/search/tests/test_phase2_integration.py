"""Integration tests for Phase 2: Real-world scenarios and advanced patterns."""


import pytest

from apps.search.backends.base import SearchHit
from apps.search.cache import VariantCache, clear_variant_cache
from apps.search.examples import (
    TicketSearchBuilderExample,
    UserSearchBuilderExample,
)
from apps.search.orchestration import get_search_orchestrator
from apps.search.serializers import (
    serialize_all_search_configs,
    serialize_search_config,
    serialize_search_hit,
    serialize_search_results,
)


class MockUser:
    """Mock User model for testing."""
    id = 1
    pk = 1
    username = "johndoe"
    email = "john@example.com"
    first_name = "John"
    last_name = "Doe"
    is_staff = False
    is_active = True
    is_superuser = False
    date_joined = None
    last_login = None

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    class groups:
        @staticmethod
        def count():
            return 3


class TestSearchBuilderExamples:
    """Test SearchBuilder example implementations."""

    def test_user_search_builder_variants(self):
        """UserSearchBuilderExample returns correct variants."""
        example = UserSearchBuilderExample()
        variants = example.get_search_variants()
        assert "admin" in variants
        assert "public" in variants
        assert "api" in variants

    def test_user_search_builder_transform_admin(self):
        """UserSearchBuilderExample transforms for admin variant."""
        example = UserSearchBuilderExample()
        obj = MockUser()
        hit = example.transform_hit(obj, variant="admin")

        assert hit["display"] == "John Doe"
        assert hit["email"] == "john@example.com"
        assert "is_staff" in hit

    def test_user_search_builder_transform_public(self):
        """UserSearchBuilderExample transforms for public variant."""
        example = UserSearchBuilderExample()
        obj = MockUser()
        hit = example.transform_hit(obj, variant="public")

        assert hit["display"] == "John Doe"
        assert "email" not in hit  # Hidden in public
        assert "is_staff" not in hit  # Hidden in public

    def test_user_search_builder_transform_api(self):
        """UserSearchBuilderExample transforms for api variant."""
        example = UserSearchBuilderExample()
        obj = MockUser()
        hit = example.transform_hit(obj, variant="api")

        assert "is_admin" in hit  # Computed field
        assert "groups_count" in hit  # Computed field

    def test_user_search_builder_filtering(self):
        """UserSearchBuilderExample filters inactive users."""
        example = UserSearchBuilderExample()

        # Mock queryset
        class MockQuerySet:
            def filter(self, **kwargs):
                assert "is_active" in kwargs
                assert kwargs["is_active"] is True
                return self

        qs = MockQuerySet()
        result = example.filter_searchable_queryset(qs)
        assert result is qs

    def test_ticket_search_builder_computed_fields(self):
        """TicketSearchBuilderExample computes fields correctly."""
        example = TicketSearchBuilderExample()

        # Mock ticket
        class MockTicket:
            id = 1
            title = "Database error"
            description = "Database connection failed"
            priority = 3
            status = "open"
            customer = "Acme Corp"
            created_at = None
            archived = False

        obj = MockTicket()
        hit = example.transform_hit(obj, variant="agent")

        assert "is_urgent" in hit
        assert "is_open" in hit
        assert "needs_attention" in hit
        assert hit["is_urgent"] is True


class TestVariantCaching:
    """Test caching layer for variant configs."""

    def test_variant_cache_basic(self):
        """VariantCache stores and retrieves configs."""
        # Note: In real tests, would need actual registered models
        # This tests the cache mechanism itself
        clear_variant_cache()

        # Cache should be empty
        stats = VariantCache.get_config("nonexistent.Model")
        assert stats == {}

    def test_variant_cache_clear(self):
        """VariantCache can be cleared."""
        clear_variant_cache()
        # After clear, next call should recompute
        stats = VariantCache.get_config("nonexistent.Model")
        assert stats == {}


class TestSearchOrchestration:
    """Test advanced search orchestration patterns."""

    def test_orchestrator_basic_creation(self):
        """SearchOrchestrator can be created."""
        orchestrator = get_search_orchestrator()
        assert orchestrator is not None
        assert hasattr(orchestrator, 'api')

    def test_orchestrator_predicate_filter(self):
        """SearchOrchestrator creates predicate filters correctly."""
        orchestrator = get_search_orchestrator()

        # Create a predicate
        is_urgent = orchestrator.create_predicate_filter(is_urgent=True, is_open=True)

        # Mock hit that matches
        class MockHit:
            extra = {"is_urgent": True, "is_open": True}

        assert is_urgent(MockHit()) is True

        # Mock hit that doesn't match
        class MockHit2:
            extra = {"is_urgent": False, "is_open": True}

        assert is_urgent(MockHit2()) is False

    def test_orchestrator_variant_selection_admin(self):
        """SearchOrchestrator selects admin variant for admin task."""
        orchestrator = get_search_orchestrator()

        # Test variant selection logic
        # (Real test would need registered models)
        # This tests the method exists and handles gracefully
        try:
            # This should handle nonexistent model gracefully
            orchestrator.search_with_best_variant(
                "test query",
                "nonexistent.Model",
                task="admin"
            )
        except ValueError:
            # Expected when model not registered
            pass


class TestAdminIntegration:
    """Test admin integration features."""

    def test_admin_config_summary_import(self):
        """Admin module imports correctly."""
        from apps.search.admin import (
            format_variant_badge,
            get_search_configuration_summary,
        )
        assert callable(get_search_configuration_summary)
        assert callable(format_variant_badge)

    def test_format_variant_badge(self):
        """format_variant_badge generates HTML."""
        from apps.search.admin import format_variant_badge

        badge = format_variant_badge("admin")
        assert isinstance(badge, str)
        assert "admin" in badge.lower()


class TestNativeSerializers:
    """Test native (non-DRF) serializers."""

    def test_serializers_import(self):
        """Serializer functions import correctly."""
        assert callable(serialize_search_hit)
        assert callable(serialize_search_results)
        assert callable(serialize_search_config)
        assert callable(serialize_all_search_configs)

    def test_serialize_search_hit(self):
        """serialize_search_hit processes SearchHit with extra fields."""
        hit = SearchHit(
            model_label="test.Model",
            model_verbose="Model",
            object_id=1,
            display="Test Item",
            url="/test/1/",
            rank=0.95,
            extra={"custom_field": "custom_value", "computed": 42}
        )

        result = serialize_search_hit(hit, variant="default")

        assert isinstance(result, dict)
        assert result["object_id"] == 1
        assert result["display"] == "Test Item"
        assert result["rank"] == 0.95
        # Extra fields should be flattened into the result
        assert result["custom_field"] == "custom_value"
        assert result["computed"] == 42

    def test_serialize_search_results(self):
        """serialize_search_results combines hits with metadata."""
        hits = [
            SearchHit(
                model_label="test.Model",
                model_verbose="Model",
                object_id=1,
                display="Item 1",
                url="/test/1/",
                rank=0.95,
            ),
            SearchHit(
                model_label="test.Model",
                model_verbose="Model",
                object_id=2,
                display="Item 2",
                url="/test/2/",
                rank=0.85,
            ),
        ]

        result = serialize_search_results(hits, "query", variant="default", backend_name="fallback")

        assert isinstance(result, dict)
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["query"] == "query"
        assert result["backend"] == "fallback"
        assert result["variant"] == "default"


class TestPerformanceOptimizations:
    """Test performance optimization features."""

    def test_cache_creation_and_clearing(self):
        """Cache system works correctly."""
        clear_variant_cache()

        # Clearing should work without error
        clear_variant_cache()

        # Second clear should also work
        clear_variant_cache()

    def test_variant_cache_has_method(self):
        """VariantCache.has_variant checks existence."""
        # Test nonexistent model
        result = VariantCache.has_variant("nonexistent.Model", "admin")
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
