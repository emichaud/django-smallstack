"""Caching layer for SearchBuilder configurations and variant lookups.

Implements memory caching with TTL (Time-To-Live) for performance optimization.
Cache is invalidated when new views are registered or configurations change.
"""

from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable, TypeVar

logger_name = "smallstack.search.cache"

F = TypeVar('F', bound=Callable[..., Any])

# In-memory cache with TTL
_config_cache: dict[str, tuple[Any, float]] = {}
_cache_ttl_seconds = 3600  # 1 hour default TTL


def set_cache_ttl(seconds: int) -> None:
    """Set cache TTL in seconds (default 3600 = 1 hour)."""
    global _cache_ttl_seconds
    _cache_ttl_seconds = seconds


def clear_variant_cache() -> None:
    """Clear all cached variant configs."""
    global _config_cache
    _config_cache.clear()


def cache_search_config(ttl: int | None = None) -> Callable[[F], F]:
    """Decorator to cache search configuration lookups.

    Args:
        ttl: Time-to-live in seconds (defaults to _cache_ttl_seconds)

    Example:
        @cache_search_config(ttl=1800)
        def get_search_config(model_label):
            ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build cache key from function and arguments
            cache_key = f"{func.__name__}:{args}:{kwargs}"

            # Check if in cache and not expired
            if cache_key in _config_cache:
                value, timestamp = _config_cache[cache_key]
                elapsed = time.time() - timestamp
                cache_ttl = ttl or _cache_ttl_seconds

                if elapsed < cache_ttl:
                    return value
                else:
                    # Expired, remove
                    del _config_cache[cache_key]

            # Not cached or expired, call function
            result = func(*args, **kwargs)

            # Cache result
            _config_cache[cache_key] = (result, time.time())
            return result

        return wrapper  # type: ignore
    return decorator


def invalidate_on_register() -> Callable[[F], F]:
    """Decorator for functions that should invalidate cache on registry changes.

    The cache is cleared whenever a new view is registered.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            # Result comes from register(), which should trigger cache clear
            clear_variant_cache()
            return result
        return wrapper  # type: ignore
    return decorator


# ============================================================================
# Cached variant lookups
# ============================================================================

class VariantCache:
    """Central cache for variant configurations."""

    @staticmethod
    @cache_search_config(ttl=3600)
    def get_config(model_label: str) -> dict[str, Any]:
        """Get cached search config for a model."""
        from .registry import get_search_config as _get_config
        return _get_config(model_label)

    @staticmethod
    @cache_search_config(ttl=3600)
    def list_all_configs() -> list[dict[str, Any]]:
        """Get cached list of all search configs."""
        from .registry import list_search_configs as _list_configs
        return _list_configs()

    @staticmethod
    def get_variants(model_label: str) -> dict[str, str]:
        """Get variants for a model from cache."""
        config = VariantCache.get_config(model_label)
        return config.get('variants', {}) if config else {}

    @staticmethod
    def has_variant(model_label: str, variant_name: str) -> bool:
        """Check if a model has a specific variant."""
        variants = VariantCache.get_variants(model_label)
        return variant_name in variants

    @staticmethod
    def clear() -> None:
        """Clear all variant caches."""
        clear_variant_cache()


# ============================================================================
# Cache statistics and monitoring
# ============================================================================

def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    stats = {
        'entries': len(_config_cache),
        'ttl_seconds': _cache_ttl_seconds,
        'cache_keys': list(_config_cache.keys())
    }
    return stats


def get_cache_hit_rate() -> float:
    """Estimate cache effectiveness (simple heuristic)."""
    if not _config_cache:
        return 0.0

    # Count non-expired entries
    now = time.time()
    valid_entries = 0
    for value, timestamp in _config_cache.values():
        if now - timestamp < _cache_ttl_seconds:
            valid_entries += 1

    return valid_entries / len(_config_cache) if _config_cache else 0.0
