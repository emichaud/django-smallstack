"""REST endpoints for the document service.

Thin skins over ``service.py`` using SmallStack's ``api_view`` (Bearer-token or
session auth + JSON parsing + response wrapping). Mounted under the runbook URLs
at ``api/documents/…``. Reads need auth; writes need an authenticated user and a
non-read-only token — the service then enforces per-runbook ownership, and a
target the caller can't view returns 404 (existence is never leaked).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from django.http import HttpRequest, JsonResponse

from apps.smallstack.api import api_error, api_view

from . import service


def _json_safe(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _result(result: service.DocumentResult) -> dict[str, Any]:
    return {k: _json_safe(v) for k, v in dataclasses.asdict(result).items()}


def _error_for(exc: service.DocumentServiceError) -> JsonResponse:
    """Map any service error to an HTTP response, uniformly across handlers.

    Every not-found variant (missing runbook, section, or document — including a
    doc/runbook hidden from the caller by the ownership rule) returns a generic
    404 with the same body, so the API never leaks whether a private slug exists.
    """
    if isinstance(exc, (service.RunbookNotFound, service.SectionNotFound, service.DocumentNotFound)):
        return api_error("Not found", 404)
    if isinstance(exc, (service.DocumentLocked, service.NotAuthorized)):
        return api_error(str(exc), 403)
    if isinstance(exc, (service.VersionConflict, service.DocumentAlreadyExists)):
        return api_error(str(exc), 409)
    return api_error(str(exc), 400)


def _require_write(request: HttpRequest) -> Optional[JsonResponse]:
    """Return an error response if the caller may not write, else None.

    Any authenticated user may attempt a write; the service enforces per-runbook
    ownership (raising ``NotAuthorized`` → 403). The token still gates read-only.
    """
    if not getattr(request.user, "is_authenticated", False):
        return api_error("Authentication required", 403)
    token = getattr(request, "_api_token", None)
    if token is not None and getattr(token, "access_level", "") == "readonly":
        return api_error("Token is read-only", 403)
    return None


@api_view(methods=["GET"])
def api_list_documents(request: HttpRequest) -> JsonResponse:
    """GET api/documents/?runbook=&source=&q="""
    docs = service.list_documents(
        runbook=request.GET.get("runbook") or None,
        source=request.GET.get("source") or None,
        query=request.GET.get("q") or None,
        viewer=request.user,
    )
    return {"results": [_result_summary(d) for d in docs]}


def _result_summary(summary: service.DocumentSummary) -> dict[str, Any]:
    return {k: _json_safe(v) for k, v in dataclasses.asdict(summary).items()}


@api_view(methods=["GET"])
def api_document_by_uid(request: HttpRequest, uid: str) -> JsonResponse:
    """GET api/documents/by-uid/<uid>/ — read by canonical uid."""
    try:
        return _result(service.get_document(uid=uid, with_body=True, viewer=request.user))
    except service.DocumentServiceError as exc:
        return _error_for(exc)


@api_view(methods=["POST"])
def api_document_move(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/move/ — re-place (or detach if to_runbook omitted)."""
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    data = request.json or {}
    try:
        result = service.move_document(
            runbook=runbook, key=key,
            to_runbook=data.get("to_runbook"),
            to_section=data.get("to_section"),
            actor=request.user,
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _result(result)


@api_view(methods=["GET", "PUT", "DELETE"])
def api_document(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """GET/PUT/DELETE api/documents/<runbook>/<key>/ — read, upsert, or delete."""
    if request.method == "GET":
        try:
            return _result(service.get_document(runbook, key, with_body=True, viewer=request.user))
        except service.DocumentServiceError as exc:
            return _error_for(exc)

    write_error = _require_write(request)
    if write_error is not None:
        return write_error

    if request.method == "DELETE":
        force = request.GET.get("force") == "true"
        try:
            service.delete_document(runbook=runbook, key=key, force=force, actor=request.user)
        except service.DocumentServiceError as exc:
            return _error_for(exc)
        return {"deleted": True, "force": force}

    data = request.json or {}
    if "body" not in data:
        return api_error("body is required", 400)
    try:
        result = service.put_document(
            runbook, key,
            body=data["body"],
            title=data.get("title"),
            section=data.get("section"),
            on_exists=data.get("on_exists", "new_version"),
            expected_version=data.get("expected_version"),
            source=data.get("source", ""),
            doc_type=data.get("doc_type", ""),
            via="api",
            actor=request.user,
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _result(result)


@api_view(methods=["POST"])
def api_document_append(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/append/ — accumulate in place."""
    write_error = _require_write(request)
    if write_error is not None:
        return write_error

    data = request.json or {}
    if "body" not in data:
        return api_error("body is required", 400)
    try:
        result = service.append_to_document(
            runbook, key, body=data["body"], source=data.get("source", ""), via="api", actor=request.user
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _result(result)


@api_view(methods=["POST"])
def api_document_archive(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/archive/ — soft-delete."""
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    try:
        return _result(service.archive_document(runbook=runbook, key=key, actor=request.user))
    except service.DocumentServiceError as exc:
        return _error_for(exc)


# -- OpenAPI schema registration ----------------------------------------------
# Hand-rolled views don't self-register the way CRUDViews do, so advertise them
# to /api/schema/openapi.json (Swagger/ReDoc) via the framework hook when present.

try:
    from apps.smallstack.api import register_api_path
except ImportError:  # pragma: no cover - older framework without the hook
    register_api_path = None

_DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "uid": {"type": "string", "description": "Canonical, container-independent address."},
        "runbook": {"type": "string", "nullable": True},
        "key": {"type": "string", "nullable": True},
        "title": {"type": "string"},
        "version": {"type": "integer"},
        "url": {"type": "string"},
        "source": {"type": "string"},
        "via": {"type": "string"},
        "is_generated": {"type": "boolean"},
        "is_archived": {"type": "boolean"},
        "locked": {"type": "boolean"},
        "updated_at": {"type": "string", "format": "date-time"},
        "content_markdown": {"type": "string", "nullable": True},
    },
}
_LIST_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": _DOC_SCHEMA}}}

_registered = False


def _json_body(schema: dict, *, required: bool = True) -> dict:
    return {"required": required, "content": {"application/json": {"schema": schema}}}


def _query(name: str, description: str) -> dict:
    return {"name": name, "in": "query", "schema": {"type": "string"}, "description": description}


def register_openapi() -> None:
    """Register the document REST surface in the OpenAPI schema (idempotent)."""
    global _registered
    if register_api_path is None or _registered:
        return
    _registered = True

    anchor = "runbook:api_documents"
    tags = ["Runbook documents"]
    p_runbook = {"name": "runbook", "in": "path", "required": True,
                 "schema": {"type": "string"}, "description": "Runbook slug."}
    p_key = {"name": "key", "in": "path", "required": True,
             "schema": {"type": "string"}, "description": "Document key (unique per runbook)."}
    p_uid = {"name": "uid", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}
    doc_ok = {"200": {"description": "The document",
                      "content": {"application/json": {"schema": _DOC_SCHEMA}}}}
    err_404 = {"404": {"description": "Not found",
                       "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}}

    register_api_path(
        anchor, methods=["GET"], summary="List / search documents", tags=tags,
        parameters=[
            _query("runbook", "Scope to a runbook slug."),
            _query("source", "Filter by provenance source."),
            _query("q", "Search title, description, and content."),
        ],
        responses={"200": {"description": "Matching documents",
                           "content": {"application/json": {"schema": _LIST_SCHEMA}}}},
    )
    register_api_path(
        anchor, subpath="by-uid/{uid}/", methods=["GET"],
        summary="Get a document by canonical uid", tags=tags, parameters=[p_uid],
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/", methods=["GET", "PUT", "DELETE"],
        summary="Get, upsert, or delete a document", tags=tags,
        parameters=[p_runbook, p_key,
                    {"name": "force", "in": "query", "schema": {"type": "boolean"},
                     "description": "DELETE: hard-delete instead of archive."}],
        request_body=_json_body({
            "type": "object", "required": ["body"],
            "properties": {
                "body": {"type": "string", "description": "Markdown content."},
                "title": {"type": "string"},
                "section": {"type": "string", "description": "Section slug."},
                "on_exists": {"type": "string", "enum": ["new_version", "overwrite", "append", "fail"],
                              "default": "new_version"},
                "expected_version": {"type": "integer", "description": "Optimistic lock."},
                "source": {"type": "string"},
                "doc_type": {"type": "string"},
            },
        }),
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/append/", methods=["POST"],
        summary="Append markdown to a document", tags=tags, parameters=[p_runbook, p_key],
        request_body=_json_body({
            "type": "object", "required": ["body"],
            "properties": {"body": {"type": "string"}, "source": {"type": "string"}},
        }),
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/move/", methods=["POST"],
        summary="Move or detach a document", tags=tags, parameters=[p_runbook, p_key],
        request_body=_json_body({
            "type": "object",
            "properties": {"to_runbook": {"type": "string", "description": "Omit to detach."},
                           "to_section": {"type": "string"}},
        }, required=False),
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/archive/", methods=["POST"],
        summary="Archive (soft-delete) a document", tags=tags, parameters=[p_runbook, p_key],
        responses={**doc_ok, **err_404},
    )


register_openapi()
