"""Search views — the HTML results page and the JSON omnibar endpoint.

Both pages live behind StaffRequiredMixin (search exposes data across
every registered model and warrants the same gate as Explorer / the
MCP admin / the API admin). Per-user search filtering by tenancy is a
future improvement that lives in the SearchBackend layer, not here.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views.generic import TemplateView, View

from apps.smallstack.mixins import StaffRequiredMixin

from .backends.base import SearchHit
from .registry import all_views, get_indexed_sources, search_all, view_count


class SearchPageView(StaffRequiredMixin, TemplateView):
    """Dedicated /smallstack/search/ HTML page.

    Results grouped by model with snippets and per-group "View more"
    links into the matching CRUDView list page (with ?q= preserved).
    """

    template_name = "search/search_page.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        query = (self.request.GET.get("q") or "").strip()
        limit_per_model = int(self.request.GET.get("limit_per_model") or 10)

        ctx["query"] = query
        ctx["registered_models"] = view_count()
        ctx["indexed_sources"] = get_indexed_sources()

        if not query:
            ctx["grouped"] = []
            ctx["total_hits"] = 0
            return ctx

        hits = search_all(query, limit_per_model=limit_per_model)
        ctx["grouped"] = group_by_model(hits)
        ctx["total_hits"] = len(hits)
        return ctx


class OmnibarSearchView(StaffRequiredMixin, View):
    """JSON endpoint for the topbar omnibar.

    Returns a compact ranked list across all models. The omnibar.js
    debounces calls and renders the response inline.
    """

    def get(self, request: HttpRequest) -> JsonResponse:
        query = (request.GET.get("q") or "").strip()
        limit = int(request.GET.get("limit") or 8)
        if not query:
            # Empty query → return discoverability payload so the
            # omnibar can show "here's what you can search" instead
            # of a blank dropdown.
            return JsonResponse({
                "query": "",
                "results": [],
                "sources": get_indexed_sources(),
                "indexed_model_count": view_count(),
            })

        hits = search_all(query, limit_per_model=max(3, limit // max(1, view_count() or 1)))
        # Trim to the requested overall limit AFTER cross-model ranking.
        hits = hits[:limit]
        return JsonResponse({
            "query": query,
            "results": [h.as_dict() for h in hits],
            "indexed_model_count": view_count(),
        })


def group_by_model(hits: list[SearchHit]) -> list[dict[str, Any]]:
    """Bucket hits by model_label preserving per-bucket rank order."""
    buckets: dict[str, list[SearchHit]] = defaultdict(list)
    label_to_verbose: dict[str, str] = {}
    for h in hits:
        buckets[h.model_label].append(h)
        label_to_verbose[h.model_label] = h.model_verbose

    # Stable order: bucket with the highest single-hit rank goes first.
    out: list[dict[str, Any]] = []
    for label in sorted(buckets, key=lambda lbl: -max(h.rank for h in buckets[lbl])):
        out.append({
            "model_label": label,
            "model_verbose": label_to_verbose[label],
            "hits": buckets[label],
            "count": len(buckets[label]),
        })
    return out


# Make registered views available to templates that need to render
# group cards even when the result set is empty for a model.
def all_indexed_views():
    return list(all_views())
