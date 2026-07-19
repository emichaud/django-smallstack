"""SearchAPI — high-level orchestration for search operations.

Enables agents and scripts to discover what's searchable, list available
variants, and compose search queries with variant selection.
"""

from __future__ import annotations

import logging
from typing import Any

from .backends import get_backend
from .backends.base import SearchHit
from .registry import (
    all_views,
    get_search_config,
    list_search_configs,
)

logger = logging.getLogger("smallstack.search")


class SearchAPI:
    """High-level search orchestration for agents and scripts.

    Provides methods to:
    - Discover search capabilities (get_config, list_variants)
    - Execute searches with variant support (search, search_and_filter)
    - Understand output schemas (get_output_schema)
    """

    def get_config(self, model_label: str) -> dict[str, Any]:
        """Get search configuration for a single model.

        Args:
            model_label: "app.Model" style identifier

        Returns:
            Dict with keys: model_label, fields, weights, variants,
            display_field, subtitle_field, has_search_builder, search_access
        """
        return get_search_config(model_label)

    def list_variants(self) -> list[dict[str, Any]]:
        """List all search configurations (including variants) across all views.

        Returns:
            List of search configs, one per registered view
        """
        return list_search_configs()

    def search(
        self,
        model_label: str,
        query: str,
        variant: str = "default",
        limit: int = 10,
    ) -> list[SearchHit]:
        """Execute a search with optional variant selection.

        Args:
            model_label: "app.Model" identifier
            query: Search query string
            variant: Output variant name (default "default")
            limit: Max results to return

        Returns:
            List of SearchHit objects

        Raises:
            ValueError: If model_label not found or query is empty
        """
        if not query or not query.strip():
            return []

        # Find the view
        view = None
        for v in all_views():
            if v.model_label == model_label:
                view = v
                break

        if not view:
            raise ValueError(f"Model {model_label} not registered for search")

        # Execute query with variant
        backend = get_backend()
        hits = backend.query(view, query, limit=limit, variant=variant)
        return hits

    def search_and_filter(
        self,
        model_label: str,
        query: str,
        filters: dict[str, Any],
        variant: str = "default",
    ) -> list[SearchHit]:
        """Search and then apply additional filtering.

        Args:
            model_label: "app.Model" identifier
            query: Search query string
            filters: Additional filter dict to apply to queryset
            variant: Output variant name (default "default")

        Returns:
            Filtered SearchHit list

        Example:
            results = api.search_and_filter(
                "support.Ticket",
                "urgent bug",
                {"status": "open"},
                variant="summary"
            )
        """
        if not query or not query.strip():
            return []

        # Find the view
        view = None
        for v in all_views():
            if v.model_label == model_label:
                view = v
                break

        if not view:
            raise ValueError(f"Model {model_label} not registered for search")

        # Get candidate IDs from search
        backend = get_backend()
        hits = backend.query(view, query, limit=1000, variant=variant)

        if not hits:
            return []

        # Apply additional filters to the queryset
        hit_ids = [h.object_id for h in hits]
        qs = view.model.objects.filter(pk__in=hit_ids)

        for key, value in filters.items():
            qs = qs.filter(**{key: value})

        # Re-hydrate hits for filtered objects
        filtered_ids = set(qs.values_list("pk", flat=True))
        return [h for h in hits if h.object_id in filtered_ids]

    def get_output_schema(self, model_label: str, variant: str = "default") -> dict[str, Any]:
        """Get the output schema for a model + variant combination.

        Args:
            model_label: "app.Model" identifier
            variant: Output variant name

        Returns:
            Dict describing the output shape of the variant
        """
        config = get_search_config(model_label)
        if not config:
            raise ValueError(f"Model {model_label} not registered for search")

        # Base SearchHit schema
        schema = {
            "type": "object",
            "properties": {
                "model_label": {"type": "string"},
                "model_verbose": {"type": "string"},
                "object_id": {"type": "integer"},
                "display": {"type": "string"},
                "subtitle": {"type": "string"},
                "snippet": {"type": "string"},
                "url": {"type": ["string", "null"]},
                "rank": {"type": "number"},
            },
            "required": ["model_label", "model_verbose", "object_id", "display"],
        }

        # If variant has custom transform_hit, note the extra fields
        if config.get("variants") and variant in config["variants"]:
            schema["properties"]["extra"] = {
                "type": "object",
                "description": f"Variant-specific fields for '{variant}' output shape"
            }

        return schema


# Convenience singleton
_api_instance: SearchAPI | None = None


def get_search_api() -> SearchAPI:
    """Get the SearchAPI singleton instance."""
    global _api_instance
    if _api_instance is None:
        _api_instance = SearchAPI()
    return _api_instance
