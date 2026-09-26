"""Scenario C REST — the thin filing endpoint a remote client needs.

    POST /api/demo/access/requests/file/

Why this exists: the generic approvals filing endpoint
(``POST /smallstack/api/approvals/requests/create/``, docs §2) accepts only
``kind``/``title``/``description``/``context``/``expires_in_minutes`` — there is
no way to point the new approval at a business object. A remote client (SPA,
service, CI job) that wants the approval linked to a row must therefore go
through an app endpoint like this one. Filed as a finding; kept thin so it can
be deleted if the generic endpoint ever grows a target.
"""

from __future__ import annotations

from typing import Any, Union

from django.http import HttpRequest, JsonResponse

from apps.smallstack.api import api_error, api_view, register_api_path

from . import services
from .models import AccessRequest

ApiResult = Union[JsonResponse, dict[str, Any], tuple[dict[str, Any], int]]


@api_view(methods=["POST"], require_auth=True)
def api_file_access_request(request: HttpRequest) -> ApiResult:
    """File an elevated-access request + its approval, from a token client.

    Readonly tokens are refused by ``api_view`` itself (this is a write).
    """
    payload = getattr(request, "json", None) or {}
    resource = str(payload.get("resource") or "").strip()
    if not resource:
        return api_error("'resource' is required.", 400)
    try:
        ar, req = services.file_access_request(
            resource=resource,
            scope=str(payload.get("scope") or AccessRequest.Scope.READ),
            reason=str(payload.get("reason") or ""),
            duration_hours=payload.get("duration_hours", 8),
            actor=request.user,
            source="REST API",
        )
    except ValueError as exc:
        return api_error(str(exc), 400)
    return {
        "access_request_id": ar.pk,
        "approval_id": req.pk,
        "state": ar.state,
        "status": req.status,
        "resource": ar.resource,
        "scope": ar.scope,
        "duration_hours": ar.duration_hours,
        "expires_at": req.expires_at.isoformat() if req.expires_at else None,
        "poll": f"/smallstack/api/approvals/requests/{req.pk}/",
        "decide": f"/smallstack/api/approvals/requests/{req.pk}/decide/",
    }, 201


# --- OpenAPI ---------------------------------------------------------------
# Anchored on the CRUD list route's bare name (build_api_urls registers
# "<url_base with dashes>-api-list").

register_api_path(
    "demo-access-requests-api-list",
    subpath="file/",
    methods=["POST"],
    summary="File an elevated-access request and its approval",
    tags=["Demo · Access"],
    request_body={
        "required": True,
        "content": {"application/json": {"schema": {
            "type": "object",
            "required": ["resource"],
            "properties": {
                "resource": {"type": "string", "description": "e.g. dataset:payroll"},
                "scope": {"type": "string", "enum": list(AccessRequest.Scope.values)},
                "reason": {"type": "string"},
                "duration_hours": {"type": "integer", "default": 8, "minimum": 1, "maximum": 720},
            },
        }}},
    },
)
