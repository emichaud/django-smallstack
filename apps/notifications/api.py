"""REST surface for notifications — the current user's inbox, machine-readable.

Two endpoints, mounted inside the app (runbook precedent):

    GET  /smallstack/notifications/api/            ?unread=1 &limit=
    POST /smallstack/notifications/api/mark-read/  {"ids": [...]} or {"all": true}

Rows are strictly recipient-scoped — there is no admin listing here; staff
debugging goes through Django admin.
"""

from __future__ import annotations

from typing import Any, Union

from django.http import HttpRequest, JsonResponse

from apps.smallstack.api import api_error, api_view, register_api_path

from . import services
from .models import Notification

# Same local alias runbook uses — a view may return a dict (wrapped by
# api_view) or a ready JsonResponse.
ApiResult = Union[JsonResponse, dict[str, Any]]

MAX_LIMIT = 200


def _serialize(n: Notification) -> dict[str, Any]:
    return {
        "id": n.pk,
        "title": n.title,
        "message": n.message,
        "url": n.url,
        "kind": n.kind,
        "actor": getattr(n.actor, "username", None),
        "read": n.is_read,
        "created_at": n.created_at.isoformat(),
    }


@api_view(methods=["GET"], require_auth=True)
def api_list_notifications(request: HttpRequest) -> ApiResult:
    # api_view guarantees an authenticated user here; the getattr-pk form
    # keeps mypy honest about the User|AnonymousUser union.
    qs = Notification.objects.filter(
        recipient_id=getattr(request.user, "pk", None)
    ).select_related("actor")
    if request.GET.get("unread") in {"1", "true"}:
        qs = qs.filter(read_at__isnull=True)
    try:
        limit = min(int(request.GET.get("limit", 50)), MAX_LIMIT)
    except ValueError:
        return api_error("limit must be an integer", 400)
    rows = list(qs[:limit])
    return {
        "count": len(rows),
        "unread_total": services.unread_count(request.user),
        "notifications": [_serialize(n) for n in rows],
    }


@api_view(methods=["POST"], require_auth=True)
def api_mark_read(request: HttpRequest) -> ApiResult:
    payload = getattr(request, "json", None) or {}
    if payload.get("all"):
        marked = services.mark_read(request.user)
    else:
        ids = payload.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            return api_error('Provide {"ids": [1, 2]} or {"all": true}.', 400)
        marked = services.mark_read(request.user, ids=ids)
    return {"marked": marked, "unread_total": services.unread_count(request.user)}


# --- OpenAPI ---------------------------------------------------------------
# Anchored on the namespaced list route (runbook "runbook:api_documents"
# precedent — register_api_path resolves the mount at schema-build time).

register_api_path(
    "notifications:api_list",
    methods=["GET"],
    summary="List the calling user's notifications",
    tags=["Notifications"],
    parameters=[
        {"name": "unread", "in": "query", "schema": {"type": "string", "enum": ["1"]},
         "description": "Only unread rows."},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50, "maximum": MAX_LIMIT}},
    ],
)
register_api_path(
    "notifications:api_list",
    subpath="mark-read/",
    methods=["POST"],
    summary="Mark the calling user's notifications read",
    tags=["Notifications"],
    # register_api_path takes a full OpenAPI RequestBody object, not a bare
    # schema (runbook's _json_body precedent).
    request_body={
        "required": True,
        "content": {"application/json": {"schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "integer"}},
                "all": {"type": "boolean"},
            },
        }}},
    },
)
