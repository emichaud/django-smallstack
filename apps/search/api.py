"""REST search: ``GET /smallstack/search/api/?q=``.

The ranked, cross-model search the omnibar and the ``search_all`` MCP tool run,
for REST clients with an API token (or a session). It calls the same
:func:`search_all` as the caller, so a hit from a view whose ``search_access``
the caller doesn't meet, or a row its ``search_visibility`` hides, is absent
here as it is in the omnibar. A per-model list's ``?q=`` is a plain substring
match over that view's ``search_fields``; this is the full-text index.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from apps.smallstack.api import api_error, api_view, register_api_path

from .registry import get_indexed_sources, search_all

MAX_LIMIT = 50


@api_view(methods=["GET"])
def search_api(request: HttpRequest) -> Any:
    query = (request.GET.get("q") or "").strip()
    if not query:
        # What may be searched, as the omnibar shows before anything is typed.
        return {"query": "", "count": 0, "results": [], "sources": get_indexed_sources(user=request.user)}
    try:
        limit = int(request.GET.get("limit") or 20)
    except ValueError:
        return api_error("limit: a whole number from 1 to 50", 400)
    if not 1 <= limit <= MAX_LIMIT:
        return api_error("limit: a whole number from 1 to 50", 400)
    model = (request.GET.get("model") or "").strip().lower()

    hits = search_all(query, limit_per_model=limit, user=request.user)
    if model:
        hits = [h for h in hits if h.model_label.lower() == model]
    hits = hits[:limit]
    return {"query": query, "count": len(hits), "results": [h.as_dict() for h in hits]}


register_api_path(
    "search:api",
    methods=["GET"],
    summary="Search every indexed model, ranked",
    tags=["Search"],
    parameters=[
        {"name": "q", "in": "query", "schema": {"type": "string"},
         "description": "The search text. Without it, the response lists what you may search (`sources`)."},
        {"name": "limit", "in": "query",
         "schema": {"type": "integer", "default": 20, "minimum": 1, "maximum": MAX_LIMIT},
         "description": "Most results to return, after ranking across models."},
        {"name": "model", "in": "query", "schema": {"type": "string"},
         "description": "Only hits from one model, by its label (`app_label.Model`, as each hit's `model_label`)."},
    ],
    responses={
        "200": {
            "description": "Hits ranked across models: model_label, object_id, display, subtitle, snippet, url, rank",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        "400": {"description": "A limit that isn't a whole number from 1 to 50"},
        "401": {"description": "No token or session"},
    },
)
