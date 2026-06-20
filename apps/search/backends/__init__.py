"""Backend selection: choose the right SearchBackend for the configured DB.

Selected once at startup; the chosen instance is cached for the process
lifetime. To force a backend in tests, monkeypatch ``_backend`` directly
or call ``reset_backend()``.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from django.conf import settings

from .base import SearchBackend

logger = logging.getLogger("smallstack.search")


@lru_cache(maxsize=1)
def get_backend() -> SearchBackend:
    """Pick a backend based on DATABASES['default']['ENGINE']."""
    engine = settings.DATABASES["default"]["ENGINE"]

    if "sqlite" in engine:
        from .sqlite_fts import SQLiteFTSBackend

        return SQLiteFTSBackend()

    if "postgresql" in engine or "postgis" in engine:
        from .postgres_fts import PostgresFTSBackend

        return PostgresFTSBackend()

    # MySQL, Oracle, anything else
    from .fallback import FallbackBackend

    logger.warning(
        "Search using FallbackBackend (__icontains). DB engine %r has no native FTS "
        "integration; search will degrade at scale. Recommended: SQLite or PostgreSQL.",
        engine,
    )
    return FallbackBackend()


def reset_backend() -> None:
    """Test helper — clears the cached backend selection."""
    get_backend.cache_clear()


__all__ = ["get_backend", "reset_backend", "SearchBackend"]
