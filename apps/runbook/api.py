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

from django.db.models import Count, Q
from django.http import HttpRequest, JsonResponse

from apps.smallstack.api import api_error, api_view

from . import permissions, service
from .models import Document


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
    if isinstance(exc, (service.VersionConflict, service.DocumentAlreadyExists, service.RunbookAlreadyExists)):
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
    """GET api/documents/?runbook=&source=&q=&limit=

    ``q`` is BM25-ranked full-text (via the shared search engine); results come
    back in relevance order and honor ``limit`` (default 50). If the search app
    isn't installed it degrades to a substring scan. Without ``q`` it's a plain
    ownership-scoped listing.
    """
    runbook = request.GET.get("runbook") or None
    source = request.GET.get("source") or None
    query = request.GET.get("q") or None
    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
    except (TypeError, ValueError):
        return api_error("'limit' must be an integer", 400)

    try:
        docs = None
        if query:
            docs = service.search_documents(
                query, viewer=request.user, runbook=runbook, source=source, limit=limit,
            )
        if docs is None:  # no query, or search engine unavailable → substring path
            docs = service.list_documents(runbook=runbook, source=source, query=query, viewer=request.user)
    except service.DocumentServiceError as exc:
        return _error_for(exc)
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


@api_view(methods=["POST"])
def api_document_unarchive(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/unarchive/ — reverse a soft-delete."""
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    try:
        return _result(service.unarchive_document(runbook=runbook, key=key, actor=request.user))
    except service.DocumentServiceError as exc:
        return _error_for(exc)


@api_view(methods=["POST"])
def api_document_revert(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/revert/ — roll back to a version.

    JSON body: ``{"to": N}`` (the version number). Snapshots that version's
    content as a new head; history is preserved.
    """
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    data = request.json or {}
    raw = data.get("to", data.get("version"))
    if raw is None:
        return api_error("'to' (version number) is required", 400)
    try:
        version = int(raw)
    except (TypeError, ValueError):
        return api_error("'to' must be an integer", 400)
    try:
        doc = service.restore_version(runbook=runbook, key=key, version=version, actor=request.user, via="api")
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _result(service.get_document(uid=str(doc.uid), with_body=True, viewer=request.user))


@api_view(methods=["POST"])
def api_document_copy(request: HttpRequest, runbook: str, key: str) -> JsonResponse:
    """POST api/documents/<runbook>/<key>/copy/ — duplicate to another location.

    JSON body: ``{"to_runbook": …, "to_key": …, "title"?, "section"?, "on_exists"?}``.
    The copy gets its own images. The destination runbook must already exist.
    """
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    data = request.json or {}
    if not data.get("to_runbook") or not data.get("to_key"):
        return api_error("'to_runbook' and 'to_key' are required", 400)
    try:
        result = service.copy_document(
            runbook=runbook, key=key, viewer=request.user,
            to_runbook=data["to_runbook"], to_key=data["to_key"],
            title=data.get("title"), section=data.get("section"),
            on_exists=data.get("on_exists", "fail"), via="api", actor=request.user,
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _result(result)


# -- Runbook resource ---------------------------------------------------------

def _runbook_summary(rb: Any) -> dict[str, Any]:
    pages = rb.n_pages if hasattr(rb, "n_pages") else rb.documents.filter(is_archived=False).count()
    return {
        "slug": rb.slug,
        "name": rb.name,
        "description": rb.description,
        "owner": rb.owner.username if rb.owner_id else None,
        "is_public": rb.is_public,
        "is_template": rb.is_template,
        "pages": pages,
    }


def _section_summary(sec: Any) -> dict[str, Any]:
    return {"slug": sec.slug, "name": sec.name, "order": sec.order}


@api_view(methods=["GET", "POST"])
def api_runbooks(request: HttpRequest) -> JsonResponse:
    """GET api/runbooks/ — list runbooks the caller may see.
    POST api/runbooks/ — create one, owned by the caller."""
    if request.method == "GET":
        rbs = permissions.viewable_runbooks(request.user).annotate(
            n_pages=Count("documents", filter=Q(documents__is_archived=False), distinct=True),
        ).order_by("name")
        return {"results": [_runbook_summary(rb) for rb in rbs]}

    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    data = request.json or {}
    slug = data.get("slug") or data.get("name")
    if not slug:
        return api_error("slug (or name) is required", 400)
    try:
        rb = service.create_runbook(
            slug, name=data.get("name"), description=data.get("description", ""),
            owner=request.user, is_public=bool(data.get("is_public", False)),
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _runbook_summary(rb)


@api_view(methods=["GET"])
def api_runbook_detail(request: HttpRequest, slug: str) -> JsonResponse:
    """GET api/runbooks/<slug>/ — runbook metadata + its table of contents
    (sections → viewable pages, sectionless grouped last)."""
    try:
        rb = service._resolve_runbook(slug)
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    if not permissions.can_view(request.user, rb):
        return api_error("Not found", 404)

    docs = service.list_documents(runbook=rb.slug, viewer=request.user)
    section_by_id = dict(
        Document.objects.filter(pk__in=[d.id for d in docs]).values_list("pk", "section__slug")
    )
    by_section: dict[Optional[str], list] = {}
    for d in docs:
        by_section.setdefault(section_by_id.get(d.id), []).append(_result_summary(d))

    data = _runbook_summary(rb)
    data["sections"] = [
        {**_section_summary(sec), "documents": by_section.get(sec.slug, [])}
        for sec in rb.sections.all().order_by("order", "name")
    ]
    data["sectionless"] = by_section.get(None, [])
    return data


@api_view(methods=["GET", "POST"])
def api_runbook_sections(request: HttpRequest, slug: str) -> JsonResponse:
    """GET api/runbooks/<slug>/sections/ — list sections.
    POST — create one (edit rights required)."""
    if request.method == "GET":
        try:
            rb = service._resolve_runbook(slug)
        except service.DocumentServiceError as exc:
            return _error_for(exc)
        if not permissions.can_view(request.user, rb):
            return api_error("Not found", 404)
        secs = rb.sections.all().order_by("order", "name")
        return {"results": [_section_summary(s) for s in secs]}

    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    data = request.json or {}
    sec_slug = data.get("slug") or data.get("name")
    if not sec_slug:
        return api_error("slug (or name) is required", 400)
    try:
        section = service.create_section(
            slug, sec_slug, name=data.get("name"), order=data.get("order", 0), actor=request.user,
        )
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _section_summary(section)


def _set_runbook_visibility(request: HttpRequest, slug: str, *, public: bool) -> JsonResponse:
    write_error = _require_write(request)
    if write_error is not None:
        return write_error
    try:
        rb = service.set_runbook_public(slug, public=public, actor=request.user)
    except service.DocumentServiceError as exc:
        return _error_for(exc)
    return _runbook_summary(rb)


@api_view(methods=["POST"])
def api_runbook_publish(request: HttpRequest, slug: str) -> JsonResponse:
    """POST api/runbooks/<slug>/publish/ — make it public (edit rights required)."""
    return _set_runbook_visibility(request, slug, public=True)


@api_view(methods=["POST"])
def api_runbook_unpublish(request: HttpRequest, slug: str) -> JsonResponse:
    """POST api/runbooks/<slug>/unpublish/ — make it private (edit rights required)."""
    return _set_runbook_visibility(request, slug, public=False)


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
            _query("q", "BM25-ranked full-text search over title, description, and content."),
            {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50},
             "description": "Max ranked results for q (capped at 200)."},
        ],
        responses={"200": {"description": "Matching documents (relevance-ordered when q is set)",
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
                "on_exists": {"type": "string",
                              "enum": ["new_version", "overwrite", "append", "append_version", "fail"],
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
    register_api_path(
        anchor, subpath="{runbook}/{key}/unarchive/", methods=["POST"],
        summary="Un-archive a document", tags=tags, parameters=[p_runbook, p_key],
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/revert/", methods=["POST"],
        summary="Roll back to an earlier version", tags=tags, parameters=[p_runbook, p_key],
        request_body=_json_body({
            "type": "object", "required": ["to"],
            "properties": {"to": {"type": "integer", "description": "Version number to roll back to."}},
        }),
        responses={**doc_ok, **err_404},
    )
    register_api_path(
        anchor, subpath="{runbook}/{key}/copy/", methods=["POST"],
        summary="Copy a document to another location", tags=tags, parameters=[p_runbook, p_key],
        request_body=_json_body({
            "type": "object", "required": ["to_runbook", "to_key"],
            "properties": {
                "to_runbook": {"type": "string"},
                "to_key": {"type": "string"},
                "title": {"type": "string"},
                "section": {"type": "string"},
                "on_exists": {"type": "string", "enum": ["fail", "overwrite", "new_version", "append"],
                              "default": "fail"},
            },
        }),
        responses={**doc_ok, **err_404},
    )

    # -- Runbook containers ---------------------------------------------------
    rb_anchor = "runbook:api_runbooks"
    rb_tags = ["Runbooks"]
    p_slug = {"name": "slug", "in": "path", "required": True,
              "schema": {"type": "string"}, "description": "Runbook slug."}
    runbook_schema = {
        "type": "object",
        "properties": {
            "slug": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "owner": {"type": "string", "nullable": True, "description": "Owner username (null = system runbook)."},
            "is_public": {"type": "boolean"},
            "is_template": {"type": "boolean"},
            "pages": {"type": "integer", "description": "Non-archived page count."},
        },
    }
    section_schema = {
        "type": "object",
        "properties": {"slug": {"type": "string"}, "name": {"type": "string"}, "order": {"type": "integer"}},
    }
    rb_ok = {"200": {"description": "The runbook",
                     "content": {"application/json": {"schema": runbook_schema}}}}

    register_api_path(
        rb_anchor, methods=["GET", "POST"], summary="List or create runbooks", tags=rb_tags,
        request_body=_json_body({
            "type": "object", "required": ["slug"],
            "properties": {
                "slug": {"type": "string", "description": "Globally unique slug (falls back to name)."},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "is_public": {"type": "boolean", "default": False},
            },
        }, required=False),
        responses={"200": {"description": "Runbooks (GET) or the created runbook (POST)",
                           "content": {"application/json": {"schema": {
                               "oneOf": [
                                   {"type": "object", "properties": {
                                       "results": {"type": "array", "items": runbook_schema}}},
                                   runbook_schema,
                               ]}}}}},
    )
    register_api_path(
        rb_anchor, subpath="{slug}/", methods=["GET"],
        summary="Runbook detail + table of contents", tags=rb_tags, parameters=[p_slug],
        responses={"200": {"description": "Runbook with grouped sections + pages",
                           "content": {"application/json": {"schema": {
                               "allOf": [runbook_schema, {"type": "object", "properties": {
                                   "sections": {"type": "array"}, "sectionless": {"type": "array"}}}]}}}},
                   **err_404},
    )
    register_api_path(
        rb_anchor, subpath="{slug}/sections/", methods=["GET", "POST"],
        summary="List or create sections", tags=rb_tags, parameters=[p_slug],
        request_body=_json_body({
            "type": "object", "required": ["slug"],
            "properties": {"slug": {"type": "string"}, "name": {"type": "string"},
                           "order": {"type": "integer", "default": 0}},
        }, required=False),
        responses={"200": {"description": "Sections (GET) or the created section (POST)",
                           "content": {"application/json": {"schema": section_schema}}}, **err_404},
    )
    register_api_path(
        rb_anchor, subpath="{slug}/publish/", methods=["POST"],
        summary="Publish a runbook (make it public)", tags=rb_tags, parameters=[p_slug],
        responses={**rb_ok, **err_404},
    )
    register_api_path(
        rb_anchor, subpath="{slug}/unpublish/", methods=["POST"],
        summary="Unpublish a runbook (make it private)", tags=rb_tags, parameters=[p_slug],
        responses={**rb_ok, **err_404},
    )


register_openapi()
