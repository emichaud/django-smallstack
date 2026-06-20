"""SearchBackend protocol — the contract every backend implements.

Three backends ship with SmallStack: SQLiteFTSBackend (FTS5 virtual
tables, BM25 ranking), PostgresFTSBackend (SearchVectorField + GIN +
ts_rank), and FallbackBackend (__icontains OR for everything else).

The user-facing API is identical across backends — write a single
CRUDView with ``enable_search = True`` and the right backend wires up
based on your configured database engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SearchHit:
    """One match returned by a backend query.

    The view layer renders these into HTML rows / JSON payloads / MCP
    tool responses. Keep this small and serializable.
    """

    model_label: str          # "support.Ticket" — content-type style id
    model_verbose: str        # "Ticket" — for UI display
    object_id: int
    display: str              # row title — comes from search_display on the view
    subtitle: str = ""        # secondary line — search_subtitle on the view
    snippet: str = ""         # short text around the matched terms
    url: str | None = None    # detail URL if available
    rank: float = 0.0         # higher = better; absolute values may differ per backend

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_label": self.model_label,
            "model_verbose": self.model_verbose,
            "object_id": self.object_id,
            "display": self.display,
            "subtitle": self.subtitle,
            "snippet": self.snippet,
            "url": self.url,
            "rank": round(self.rank, 4),
        }


@dataclass
class IndexedView:
    """A CRUDView that has opted into search via ``enable_search = True``.

    Held in the search registry and consulted by every backend at query
    time. The backend translates this into its native indexing strategy
    (FTS5 virtual table, GIN-indexed SearchVector column, or just a
    queryset filter for the fallback).
    """

    view_cls: type
    model: type
    fields: list[str]                            # search_fields
    weights: dict[str, int] = field(default_factory=dict)  # search_weight
    display_field: str | None = None             # search_display
    subtitle_field: str | None = None            # search_subtitle

    @property
    def model_label(self) -> str:
        return f"{self.model._meta.app_label}.{self.model.__name__}"

    @property
    def model_verbose(self) -> str:
        return str(self.model._meta.verbose_name).title()


@runtime_checkable
class SearchBackend(Protocol):
    """Every backend implements this protocol. Methods are blocking — the
    caller is responsible for thread / async concerns.

    Index-maintenance methods (``index_object`` / ``remove_object`` /
    ``rebuild``) are no-ops for backends that don't need a separate
    index (FallbackBackend reads model columns directly at query time).
    """

    name: str  # human-readable backend name for diagnostics

    def ensure_index(self, view: IndexedView) -> None:
        """Create/migrate the index structure for an indexed view.

        Called once per registered view at startup. Idempotent — backends
        check whether the index already exists before creating.
        """
        ...

    def index_object(self, view: IndexedView, obj: Any) -> None:
        """Insert or update one object in the index."""
        ...

    def remove_object(self, view: IndexedView, object_id: int) -> None:
        """Delete one object from the index."""
        ...

    def rebuild(self, view: IndexedView) -> int:
        """Drop and rebuild the index from the model's current rows.

        Returns the row count indexed. Used by the
        ``rebuild_search_index`` management command.
        """
        ...

    def query(
        self,
        view: IndexedView,
        query: str,
        limit: int = 10,
    ) -> list[SearchHit]:
        """Run a search against this view's index and return ranked hits."""
        ...
