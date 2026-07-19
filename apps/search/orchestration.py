"""Advanced search orchestration patterns for agents and complex workflows.

Enables multi-stage search, composed queries, and intelligent variant selection
for agents that need to execute complex search operations.
"""

from __future__ import annotations

from typing import Any, Callable

from .api import SearchAPI
from .backends.base import SearchHit
from .cache import VariantCache


class SearchOrchestrator:
    """High-level orchestrator for complex multi-stage search workflows.

    Enables agents to:
    - Execute multi-stage searches (broad → filtered → ranked)
    - Compose results from multiple models
    - Intelligently select variants based on task requirements
    - Chain search operations with predicates
    """

    def __init__(self) -> None:
        self.api = SearchAPI()

    # ========================================================================
    # Multi-Stage Search Patterns
    # ========================================================================

    def search_broad_then_filter(
        self,
        model_label: str,
        query: str,
        variant: str = "default",
        filter_fn: Callable[[SearchHit], bool] | None = None,
        limit: int = 50
    ) -> list[SearchHit]:
        """Execute broad search then filter results with predicate.

        Stage 1: Get many results from search (no limit restriction)
        Stage 2: Filter with predicate function
        Stage 3: Return limited results

        Args:
            model_label: Target model to search
            query: Search query
            variant: Output variant
            filter_fn: Predicate function(hit) -> bool
            limit: Max results to return

        Returns:
            Filtered search results

        Example:
            # Find urgent open tickets
            results = orchestrator.search_broad_then_filter(
                "tickets.Ticket",
                "important",
                variant="detail",
                filter_fn=lambda h: h.extra.get("is_urgent", False),
                limit=10
            )
        """
        # Stage 1: Get broad results
        hits = self.api.search(model_label, query, variant=variant, limit=100)

        # Stage 2: Filter with predicate
        if filter_fn:
            hits = [h for h in hits if filter_fn(h)]

        # Stage 3: Limit results
        return hits[:limit]

    def search_refine_by_filters(
        self,
        model_label: str,
        query: str,
        filters: dict[str, Any],
        variant: str = "default"
    ) -> list[SearchHit]:
        """Search and refine with field-based filters.

        Simpler than search_broad_then_filter for standard filters.

        Args:
            model_label: Target model
            query: Search query
            filters: Dict of field filters (e.g., {"status": "open"})
            variant: Output variant

        Returns:
            Filtered search results

        Example:
            results = orchestrator.search_refine_by_filters(
                "tickets.Ticket",
                "database error",
                {"status": "open", "priority__gte": 2},
                variant="summary"
            )
        """
        return self.api.search_and_filter(
            model_label, query, filters, variant=variant
        )

    # ========================================================================
    # Multi-Model Composition Patterns
    # ========================================================================

    def search_across_models(
        self,
        query: str,
        model_labels: list[str],
        variant: str = "default",
        limit_per_model: int = 5
    ) -> dict[str, list[SearchHit]]:
        """Search across multiple models and return results per model.

        Args:
            query: Search query
            model_labels: List of model labels to search
            variant: Output variant for all searches
            limit_per_model: Max results per model

        Returns:
            Dict mapping model_label -> list of SearchHit

        Example:
            results = orchestrator.search_across_models(
                "urgent issue",
                ["users.User", "tickets.Ticket", "help.Article"],
                variant="summary",
                limit_per_model=5
            )
            # results = {
            #     "users.User": [...],
            #     "tickets.Ticket": [...],
            #     "help.Article": [...]
            # }
        """
        results = {}
        for model_label in model_labels:
            try:
                hits = self.api.search(
                    model_label, query, variant=variant, limit=limit_per_model
                )
                results[model_label] = hits
            except ValueError:
                # Model not registered, skip
                results[model_label] = []

        return results

    def search_and_combine(
        self,
        query: str,
        model_labels: list[str],
        variant: str = "default",
        rank_fn: Callable[[SearchHit], float] | None = None,
        limit: int = 20
    ) -> list[SearchHit]:
        """Search across models and combine results with optional reranking.

        Args:
            query: Search query
            model_labels: Models to search
            variant: Output variant
            rank_fn: Optional custom ranking function(hit) -> score
            limit: Max total results

        Returns:
            Combined ranked list of hits

        Example:
            # Combine user + ticket search, sort by custom score
            results = orchestrator.search_and_combine(
                "john",
                ["users.User", "tickets.Ticket"],
                variant="summary",
                rank_fn=lambda h: (
                    10 if h.model_label == "users.User" else 5 +
                    (h.rank or 0)  # Boost users, then by search rank
                ),
                limit=10
            )
        """
        # Stage 1: Search all models
        all_hits = []
        for model_label in model_labels:
            try:
                hits = self.api.search(model_label, query, variant=variant, limit=100)
                all_hits.extend(hits)
            except ValueError:
                continue

        # Stage 2: Rerank if custom function provided
        if rank_fn:
            all_hits.sort(key=rank_fn, reverse=True)
        else:
            # Default: sort by rank (higher is better)
            all_hits.sort(key=lambda h: h.rank, reverse=True)

        # Stage 3: Limit results
        return all_hits[:limit]

    # ========================================================================
    # Intelligent Variant Selection Patterns
    # ========================================================================

    def search_with_best_variant(
        self,
        query: str,
        model_label: str,
        task: str = "general",
        limit: int = 10
    ) -> list[SearchHit]:
        """Search using the best variant for a task.

        Task hints guide variant selection:
        - "admin" → selects "admin" or "detail" variant
        - "api" → selects "api" or "agent" variant
        - "ui" → selects "summary" or "browse" variant
        - "export" → selects "export" or "csv" variant

        Args:
            query: Search query
            model_label: Model to search
            task: Task hint ("admin", "api", "ui", "export", or "general")
            limit: Max results

        Returns:
            Search results in best variant for task

        Example:
            # For admin task, automatically use "admin" variant if available
            results = orchestrator.search_with_best_variant(
                "user accounts",
                "users.User",
                task="admin",
                limit=20
            )
        """
        variants = VariantCache.get_variants(model_label)

        # Map task to variant preferences (in order)
        task_variant_map = {
            "admin": ["admin", "detail", "default"],
            "api": ["api", "agent", "default"],
            "ui": ["summary", "browse", "default"],
            "export": ["export", "csv", "detail", "default"],
            "general": ["default", "summary", "api"]
        }

        # Find first available variant for task
        preferred_variants = task_variant_map.get(task, ["default"])
        selected_variant = "default"
        for variant in preferred_variants:
            if variant in variants or variant == "default":
                selected_variant = variant
                break

        return self.api.search(model_label, query, variant=selected_variant, limit=limit)

    def search_across_models_with_best_variants(
        self,
        query: str,
        task: str = "general",
        limit_per_model: int = 5
    ) -> dict[str, list[SearchHit]]:
        """Search all models using best variant for task.

        Args:
            query: Search query
            task: Task hint (shapes variant selection per model)
            limit_per_model: Max results per model

        Returns:
            Dict mapping model_label -> list of SearchHit

        Example:
            # For admin task, automatically selects best "admin"-like
            # variant for each model
            results = orchestrator.search_across_models_with_best_variants(
                "john doe",
                task="admin",
                limit_per_model=10
            )
        """
        configs = VariantCache.list_all_configs()
        results = {}

        for config in configs:
            model_label = config['model_label']
            try:
                hits = self.search_with_best_variant(
                    query, model_label, task=task, limit=limit_per_model
                )
                results[model_label] = hits
            except ValueError:
                results[model_label] = []

        return results

    # ========================================================================
    # Predicate-Based Filtering
    # ========================================================================

    def create_predicate_filter(
        self,
        **conditions: Any
    ) -> Callable[[SearchHit], bool]:
        """Create a predicate function from conditions.

        Checks SearchHit.extra fields for conditions.

        Args:
            **conditions: Field=value conditions

        Returns:
            Function that returns True if all conditions match

        Example:
            is_urgent_and_open = orchestrator.create_predicate_filter(
                is_urgent=True,
                is_open=True
            )

            urgent_open = orchestrator.search_broad_then_filter(
                "tickets.Ticket",
                "database",
                filter_fn=is_urgent_and_open
            )
        """
        def predicate(hit: SearchHit) -> bool:
            for field, expected_value in conditions.items():
                actual_value = hit.extra.get(field)
                if actual_value != expected_value:
                    return False
            return True

        return predicate


# Singleton instance for easy access
_orchestrator: SearchOrchestrator | None = None


def get_search_orchestrator() -> SearchOrchestrator:
    """Get the SearchOrchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SearchOrchestrator()
    return _orchestrator
