"""Search result serialization helpers (native dict/JSON, no DRF dependency).

Provides functions to serialize SearchHit, search configs, and results to JSON-safe dicts.
SmallStack uses native REST (no DRF), so all serialization is explicit dict construction.
"""

from __future__ import annotations

from typing import Any

from .backends.base import SearchHit
from .registry import get_search_config, list_search_configs


def serialize_search_hit(hit: SearchHit, variant: str = "default") -> dict[str, Any]:
    """Serialize a SearchHit to a JSON-safe dictionary.

    Args:
        hit: SearchHit object to serialize
        variant: Variant name for reference

    Returns:
        Dict with all fields including extra variant data
    """
    return {
        "model_label": hit.model_label,
        "model_verbose": hit.model_verbose,
        "object_id": hit.object_id,
        "display": hit.display,
        "subtitle": hit.subtitle,
        "snippet": hit.snippet,
        "url": hit.url,
        "rank": round(hit.rank, 4),
        **(hit.extra or {})  # Include variant-specific fields
    }


def serialize_search_results(
    hits: list[SearchHit],
    query: str = "",
    variant: str = "default",
    backend_name: str = ""
) -> dict[str, Any]:
    """Serialize complete search results to JSON.

    Args:
        hits: List of SearchHit objects
        query: The search query string
        variant: The variant used
        backend_name: Name of the backend

    Returns:
        Dict with results, metadata, and pagination info
    """
    return {
        "results": [serialize_search_hit(h, variant) for h in hits],
        "total": len(hits),
        "query": query,
        "variant": variant,
        "backend": backend_name,
    }


def serialize_search_config(model_label: str) -> dict[str, Any] | None:
    """Serialize configuration for a single model.

    Args:
        model_label: "app.Model" identifier

    Returns:
        Dict with config, or None if model not found
    """
    config = get_search_config(model_label)
    if not config:
        return None

    return {
        "model_label": config.get("model_label"),
        "model_verbose": config.get("model_verbose"),
        "fields": config.get("fields", []),
        "weights": config.get("weights", {}),
        "variants": config.get("variants", {}),
        "display_field": config.get("display_field"),
        "subtitle_field": config.get("subtitle_field"),
        "has_search_builder": config.get("has_search_builder", False),
        "search_access": config.get("search_access"),
    }


def serialize_all_search_configs() -> dict[str, Any]:
    """Serialize all search configurations.

    Returns:
        Dict with list of configs and metadata
    """
    from .backends import get_backend

    configs = list_search_configs()
    backend = get_backend()

    return {
        "total": len(configs),
        "configs": [serialize_search_config(c["model_label"]) for c in configs],
        "backend": backend.name,
    }
