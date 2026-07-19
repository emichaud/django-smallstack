"""SearchBuilder protocol — optional interface for customizing search per-CRUDView.

A CRUDView can optionally implement SearchBuilder to customize:
- Which fields get indexed
- How results are transformed (variants)
- Ranking weights
- What gets indexed (filtering)

If not implemented, search uses defaults (backward compatible).
"""

from __future__ import annotations

from typing import Any, Protocol

from django.db.models import QuerySet


class SearchBuilder(Protocol):
    """Optional protocol for CRUDView to customize search behavior.

    Implement any or all of these methods to customize how search works:
    - get_search_variants() — Define output shapes (default, summary, mcp, etc.)
    - transform_hit() — Reshape objects for different use cases
    - filter_searchable_queryset() — Control what gets indexed (e.g., published=True)
    - get_ranking_weights() — Custom relevance scoring per field

    Example:
        class TicketCRUDView(CRUDView):
            model = Ticket
            enable_search = True
            search_fields = ["title", "description"]

            def get_search_variants(self) -> dict[str, str]:
                return {
                    "default": "Full ticket with description",
                    "summary": "Title + customer only",
                    "mcp": "Matches create_ticket tool"
                }

            def transform_hit(self, obj: Any, variant: str = "default") -> dict:
                if variant == "summary":
                    return {"title": obj.title, "customer": obj.customer.name}
                elif variant == "mcp":
                    return {
                        "id": obj.id,
                        "title": obj.title,
                        "customer_id": obj.customer.id,
                        "status": obj.status
                    }
                else:
                    return {
                        "display": obj.title,
                        "subtitle": obj.description,
                        "customer": obj.customer.name,
                        "status": obj.status
                    }

            def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
                # Only index non-archived tickets
                return qs.filter(archived=False)

            def get_ranking_weights(self) -> dict[str, int]:
                return {"title": 3, "description": 2, "customer__name": 1}
    """

    def get_search_variants(self) -> dict[str, str]:
        """Return available output variants for this model.

        Each variant describes a different shape of search result.
        Enables agents and UI to request the right data for their use case.

        Returns:
            Dict mapping variant name (str) → description (str).
            Must include at least a "default" variant.

        Example:
            {
                "default": "Full ticket with description and customer",
                "summary": "Quick lookup - title + customer only",
                "mcp": "Matches create_ticket MCP tool schema"
            }
        """
        ...

    def transform_hit(self, obj: Any, variant: str = "default") -> dict[str, Any]:
        """Transform a model instance to a search result dict.

        Called by backends to convert the object to the requested output shape.
        The dict is converted to SearchHit or returned as-is depending on context.

        Args:
            obj: The model instance being rendered
            variant: Output variant name (e.g., "default", "summary", "mcp").
                    Defaults to "default" if not specified by the caller.

        Returns:
            Dict to be returned as search result.
            For SearchHit compatibility, include "display" key when possible.
            Can include any other fields (they'll be stored in SearchHit.extra).

        Example:
            def transform_hit(self, obj, variant="default"):
                if variant == "summary":
                    return {
                        "display": obj.title,
                        "subtitle": obj.customer.name
                    }
                elif variant == "mcp":
                    return {
                        "id": obj.id,
                        "title": obj.title,
                        "customer_id": obj.customer.id,
                        "status": obj.status,
                        "priority": obj.priority
                    }
                else:  # default
                    return {
                        "display": obj.title,
                        "subtitle": obj.description,
                        "customer": obj.customer.name,
                        "status": obj.status
                    }
        """
        ...

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        """Filter what gets indexed.

        Called before indexing to exclude rows that shouldn't be searchable.
        Examples: only index published posts, non-archived tickets, active users.

        Args:
            qs: Unfiltered queryset for the model

        Returns:
            Filtered queryset containing only rows that should be indexed

        Example:
            def filter_searchable_queryset(self, qs):
                # Only index non-archived, published tickets
                return qs.filter(archived=False, published=True)
        """
        ...

    def get_ranking_weights(self) -> dict[str, int]:
        """Per-field ranking weights for relevance.

        Higher weight = higher ranking when the field matches.
        Applies to BM25 (SQLite FTS5) and ts_rank (PostgreSQL) scoring.

        Args:
            None

        Returns:
            Dict mapping field name (str) → weight (int, typically 1-3).
            Fields not listed default to weight 1.

        Example:
            def get_ranking_weights(self):
                return {
                    "title": 3,           # Most important
                    "customer__name": 2,  # Medium importance
                    "description": 1      # Lowest importance (or omit)
                }
        """
        ...
