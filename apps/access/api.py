"""The Access REST surface, at ``/smallstack/api/access/``.

Reads answer what the Access pages show, as JSON, for a script, a ticketing
system or an auditor's tooling. The one write, membership, goes through
:func:`apps.access.services.set_membership` like every other surface, so it is
checked and recorded the same way.

    GET    api/access/users/                      accounts, with groups and counts
    GET    api/access/users/{user}/               one account: groups, permissions with sources, changes
    GET    api/access/users/{user}/check/?perm=   has_perm, with the reasons
    PUT    api/access/users/{user}/groups/{group}/  add to the group
    DELETE api/access/users/{user}/groups/{group}/  remove from it
    DELETE api/access/users/{user}/permissions/{perm}/  take a direct permission off (no PUT: use a group)
    GET    api/access/groups/                     groups, with drift against the code
    POST   api/access/groups/                     create one: {"name": ...}
    GET    api/access/groups/{group}/             one group: members, permissions
    PATCH  api/access/groups/{group}/             rename: {"name": ...}
    DELETE api/access/groups/{group}/             delete (members keep their accounts)
    PUT    api/access/groups/{group}/permissions/{perm}/  grant the permission (you must hold it)
    DELETE api/access/groups/{group}/permissions/{perm}/  take it away
    GET    api/access/findings/                   the least-privilege findings
    GET    api/access/events/?who=&kind=&limit=   the change log
    GET    api/access/reviews/?status=            periodic access reviews (attestations)
    GET    api/access/reviews/{id}/               one review: roster, decisions, signature
    GET    api/access/evidence/?from=&to=&scope=  the audit pack (JSON; &format=zip for the bundle)
    GET    api/access/evidence/packs/[{id}/]      stored packs with their SHA-256 (&format=zip for the file)
    GET    api/access/reviews/cadence/            where the periodic review stands, and its schedule

``{user}`` is a username, email or id; ``{group}`` a name or id. Reads need a
staff account holding ``accounts.view_user`` (any token tier; superusers
pass); the write needs an auth-level token *and*
``accounts.change_user``, the bar the account endpoints set.
"""

from __future__ import annotations

from typing import Any, Union

from django.http import HttpRequest, HttpResponse, JsonResponse

from apps.smallstack.api import api_error, api_view, register_api_path

from . import services
from .registry import run_checks

ApiResult = Union[JsonResponse, dict[str, Any], tuple[dict[str, Any], int]]

_LIMIT_DEFAULT = 100
_LIMIT_MAX = 1000


def _read_refusal(request: HttpRequest) -> JsonResponse | None:
    """403 unless the caller may read access (``services.can_read_access``)."""
    if services.can_read_access(request.user):
        return None
    return api_error(services.READ_ACCESS_REFUSAL, 403)


def _limit(request: HttpRequest) -> int:
    try:
        return max(1, min(int(request.GET.get("limit", _LIMIT_DEFAULT)), _LIMIT_MAX))
    except (TypeError, ValueError):
        return _LIMIT_DEFAULT


# --- Users --------------------------------------------------------------------


@api_view(methods=["GET"], require_staff=True)
def api_users(request: HttpRequest) -> ApiResult:
    """Accounts with their groups and counts; ``?q=`` searches name, email and
    group, ``?show=active|staff|inactive|all`` (default active)."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from django.db.models import Q

    q = request.GET.get("q", "").strip()
    show = request.GET.get("show", "active")
    qs = services.users_with_access()
    if show == "active":
        qs = qs.filter(is_active=True)
    elif show == "staff":
        qs = qs.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
    elif show == "inactive":
        qs = qs.filter(is_active=False)
    elif show != "all":
        return api_error("show must be active, staff, inactive or all.", 400)
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(groups__name__icontains=q)
        ).distinct()
    limit = _limit(request)
    rows = [
        {
            "username": u.get_username(),
            "email": u.email or "",
            "active": u.is_active,
            "staff": u.is_staff,
            "superuser": u.is_superuser,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "groups": sorted(g.name for g in u.groups.all()),
            "direct_permissions": u.direct_permission_count,
            "active_tokens": u.active_token_count,
        }
        for u in qs[:limit]
    ]
    return {"count": qs.count(), "results": rows}


@api_view(methods=["GET"], require_staff=True)
def api_user(request: HttpRequest, user: str) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    try:
        target = services.resolve_user(user)
    except LookupError as exc:
        return api_error(str(exc), 404)
    return services.user_payload(target, events=_limit(request) if "limit" in request.GET else 10)


@api_view(methods=["GET"], require_staff=True)
def api_user_check(request: HttpRequest, user: str) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    perm = request.GET.get("perm", "").strip()
    if "." not in perm:
        return api_error("perm is required, as app_label.codename.", 400)
    try:
        target = services.resolve_user(user)
    except LookupError as exc:
        return api_error(str(exc), 404)
    return services.explanation_payload(target, perm)


@api_view(methods=["PUT", "DELETE"], require_staff=True, require_auth_token=True)
def api_user_group(request: HttpRequest, user: str, group: str) -> ApiResult:
    """PUT adds the account to the group, DELETE removes it. Idempotent: the
    reply's ``changed`` says whether anything happened."""
    if not request.user.has_perm(services.CHANGE_MEMBERSHIP):
        return api_error(f"{services.CHANGE_MEMBERSHIP} is required to change membership.", 403)
    try:
        target = services.resolve_user(user)
        grp = services.resolve_group(group)
    except LookupError as exc:
        return api_error(str(exc), 404)
    member = request.method == "PUT"
    try:
        changed = services.set_membership(target, grp, member, actor=request.user, source="rest")
    except services.MembershipRefused as exc:
        return api_error(str(exc), 403)
    return {"username": target.get_username(), "group": grp.name, "member": member, "changed": changed}


@api_view(methods=["DELETE"], require_staff=True, require_auth_token=True)
def api_user_permission(request: HttpRequest, user: str, perm: str) -> ApiResult:
    """Take a direct permission off the account (there is no PUT: grant
    through a group). Idempotent."""
    try:
        target = services.resolve_user(user)
    except LookupError as exc:
        return api_error(str(exc), 404)
    try:
        changed = services.remove_direct_permission(target, perm, actor=request.user, source="rest")
    except services.GroupRefused as exc:
        return api_error(str(exc), exc.status)
    return {"username": target.get_username(), "permission": perm, "held": False, "changed": changed}


def _posted_name(request: HttpRequest) -> str:
    """``name`` from the JSON body ``api_view`` parsed onto the request."""
    body = getattr(request, "json", None) or {}
    return str(body.get("name", "")) if isinstance(body, dict) else ""


# --- Groups ---------------------------------------------------------------------
# Reads for any staff reader; the writes (what the group page does) need an
# auth-level token and the matching auth.*_group permission, through the
# same services as the page, recorded from ``rest``.


@api_view(methods=["GET"], require_staff=True)
def _groups_read(request: HttpRequest) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    return {"results": [services.group_payload(g, members=False) for g in services.groups_with_counts()]}


@api_view(methods=["POST"], require_staff=True, require_auth_token=True)
def _groups_create(request: HttpRequest) -> ApiResult:
    """``{"name": "..."}`` → 201 with the group."""
    try:
        grp = services.create_group(_posted_name(request), actor=request.user, source="rest")
    except services.GroupRefused as exc:
        return api_error(str(exc), exc.status)
    return services.group_payload(grp), 201


def api_groups(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    """GET lists; POST creates."""
    view = _groups_create if request.method == "POST" else _groups_read
    return view(request, *args, **kwargs)  # type: ignore[no-any-return]


@api_view(methods=["GET"], require_staff=True)
def _group_read(request: HttpRequest, group: str) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    try:
        grp = services.resolve_group(group)
    except LookupError as exc:
        return api_error(str(exc), 404)
    return services.group_payload(grp)


@api_view(methods=["PATCH", "DELETE"], require_staff=True, require_auth_token=True)
def _group_write(request: HttpRequest, group: str) -> ApiResult:
    """PATCH ``{"name": "..."}`` renames; DELETE deletes (members keep their accounts)."""
    try:
        grp = services.resolve_group(group)
    except LookupError as exc:
        return api_error(str(exc), 404)
    try:
        if request.method == "DELETE":
            name = grp.name
            services.delete_group(grp, actor=request.user, source="rest")
            return {"group": name, "deleted": True}
        changed = services.rename_group(grp, _posted_name(request), actor=request.user, source="rest")
    except services.GroupRefused as exc:
        return api_error(str(exc), exc.status)
    return {**services.group_payload(grp, members=False), "changed": changed}


def api_group(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    """GET reads; PATCH renames; DELETE deletes."""
    view = _group_write if request.method in ("PATCH", "DELETE") else _group_read
    return view(request, *args, **kwargs)  # type: ignore[no-any-return]


@api_view(methods=["PUT", "DELETE"], require_staff=True, require_auth_token=True)
def api_group_permission(request: HttpRequest, group: str, perm: str) -> ApiResult:
    """PUT grants ``perm`` (``app_label.codename``) to the group, DELETE takes
    it away. Granting needs the caller to hold it. Idempotent."""
    try:
        grp = services.resolve_group(group)
    except LookupError as exc:
        return api_error(str(exc), 404)
    held = request.method == "PUT"
    try:
        changed = services.set_group_permission(grp, perm, held, actor=request.user, source="rest")
    except services.GroupRefused as exc:
        return api_error(str(exc), exc.status)
    return {"group": grp.name, "permission": perm, "held": held, "changed": changed}


# --- The review and the log ------------------------------------------------------


@api_view(methods=["GET"], require_staff=True)
def api_findings(request: HttpRequest) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    findings = run_checks()
    order = {"danger": 3, "warning": 2, "info": 1, "ok": 0}
    worst = max(findings, key=lambda f: order[f.severity], default=None)
    return {"worst": worst.severity if worst else "ok", "findings": [f.as_dict() for f in findings]}


@api_view(methods=["GET"], require_staff=True)
def api_events(request: HttpRequest) -> ApiResult:
    """The change log, newest first; ``?who=`` matches actor, subject, group
    or permission, ``?kind=`` one kind or a family (``grants``, ``removals``,
    ``accounts``, ``groups``, ``credentials``, ``reviews``), ``?ordering=``
    a column of the Changes page (``at``, ``kind``, ``subject``, ``what``,
    ``actor``, ``source``; ``-`` reverses)."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from .views import _events_queryset

    qs = _events_queryset(request)
    return {"count": qs.count(), "results": services.event_payloads(qs[: _limit(request)])}


# --- Access reviews (read-only: deciding and signing are a person's act on the page) ---


@api_view(methods=["GET"], require_staff=True)
def api_reviews(request: HttpRequest) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import reviews
    from .models import AccessReview

    qs = AccessReview.objects.all()
    status = request.GET.get("status", "")
    if status in AccessReview.Status.values:
        qs = qs.filter(status=status)
    return {"results": [reviews.review_payload(r, items=False) for r in qs[: _limit(request)]]}


@api_view(methods=["GET"], require_staff=True)
def api_review(request: HttpRequest, review_id: int) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import reviews
    from .models import AccessReview

    review = AccessReview.objects.filter(pk=review_id).first()
    if review is None:
        return api_error(f"No review #{review_id}.", 404)
    return reviews.review_payload(review)


# --- Evidence (read-only) -----------------------------------------------------------


@api_view(methods=["GET"], require_staff=True)
def api_evidence(request: HttpRequest) -> ApiResult | HttpResponse:
    """The audit pack for ``?from=&to=`` (``?scope=privileged|all``), every
    sheet as JSON; ``?format=zip`` is the bundle (cover.md, CSVs, JSON)."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import evidence
    from .views import EvidenceArgsError, _evidence_args

    if not (request.GET.get("from") and request.GET.get("to")):
        return api_error("from and to (YYYY-MM-DD) are required.", 400)
    fmt = request.GET.get("format", "json")
    if fmt not in ("json", "zip"):
        return api_error("format must be json or zip.", 400)
    try:
        start, end, scope = _evidence_args(request)
    except EvidenceArgsError as exc:
        return api_error(str(exc), 400)
    pack = evidence.build(start, end, scope=scope, generated_by=request.user)
    if fmt == "zip":
        import hashlib

        data = evidence.bundle_zip(pack)
        response = HttpResponse(data, content_type="application/zip")
        response["X-Content-SHA256"] = hashlib.sha256(data).hexdigest()  # G-1
        response["Content-Disposition"] = f'attachment; filename="{evidence.bundle_name(pack)}.zip"'
        return response
    return pack.as_dict()


@api_view(methods=["GET"], require_staff=True)
def api_evidence_packs(request: HttpRequest) -> ApiResult:
    """The stored packs (built when a quarter closed, when a review was signed,
    or on request), newest first: period, scope, reason, size, SHA-256."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import cadence
    from .models import EvidenceBundle

    qs = EvidenceBundle.objects.all()
    scope = request.GET.get("scope", "")
    if scope:
        qs = qs.filter(scope=scope)
    return {"results": [cadence.bundle_payload(b) for b in qs[: _limit(request)]]}


@api_view(methods=["GET"], require_staff=True)
def api_evidence_pack(request: HttpRequest, pack_id: int) -> ApiResult | HttpResponse:
    """One stored pack: its metadata, or ``?format=zip`` for the file as stored
    (the ``X-Content-SHA256`` header carries the digest to check it against)."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import cadence
    from .models import EvidenceBundle

    bundle = EvidenceBundle.objects.filter(pk=pack_id).first()
    if bundle is None:
        return api_error(f"No evidence pack #{pack_id}.", 404)
    if request.GET.get("format") == "zip":
        from .views import bundle_response

        return bundle_response(bundle)
    return cadence.bundle_payload(bundle)


@api_view(methods=["GET"], require_staff=True)
def api_review_cadence(request: HttpRequest) -> ApiResult:
    """Where the periodic review stands: the last complete quarter (signed,
    open or not reviewed), when it is due, the last signing, the schedule."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from . import cadence, reviews

    s = cadence.status()
    job = s["job"]
    return {
        "cadence": s["cadence"],
        "enabled": s["enabled"],
        "scope": s["scope"],
        "period": {
            "label": s["period"].label,
            "start": s["period"].start.isoformat(),
            "end": s["period"].end.isoformat(),
        },
        "signed": reviews.review_payload(s["signed"], items=False) if s["signed"] else None,
        "open": reviews.review_payload(s["open"], items=False) if s["open"] else None,
        "due": s["due"].isoformat(),
        "days_until_due": s["days_until_due"],
        "last_signed": reviews.review_payload(s["last_signed"], items=False) if s["last_signed"] else None,
        "next_close": s["next_close"].isoformat(),
        "schedule": (
            {
                "name": job.name,
                "enabled": job.enabled,
                "next_run_at": job.next_run_at.isoformat() if getattr(job, "next_run_at", None) else None,
                "last_run_at": job.last_run_at.isoformat() if getattr(job, "last_run_at", None) else None,
            }
            if job is not None
            else None
        ),
    }


# --- OpenAPI ----------------------------------------------------------------------

_TAG = ["Access"]
_ERR = {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}
_USER = {
    "name": "user",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Username, email or id.",
}
_GROUP = {
    "name": "group",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "Group name or id.",
}
_LIMIT = {
    "name": "limit",
    "in": "query",
    "schema": {"type": "integer", "default": _LIMIT_DEFAULT, "maximum": _LIMIT_MAX},
}


def _ok(description: str) -> dict[str, Any]:
    return {"description": description, "content": {"application/json": {"schema": {"type": "object"}}}}


register_api_path(
    "access-api-users",
    methods=["GET"],
    summary="Accounts with their groups, direct permissions and live tokens",
    tags=_TAG,
    parameters=[
        {"name": "q", "in": "query", "schema": {"type": "string"}},
        {"name": "show", "in": "query", "schema": {"type": "string", "enum": ["active", "staff", "inactive", "all"]}},
        _LIMIT,
    ],
    responses={"200": _ok("Accounts"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-users",
    subpath="{user}/",
    methods=["GET"],
    summary="One account: groups (since, by whom), every permission with its sources, recent changes",
    tags=_TAG,
    parameters=[_USER, _LIMIT],
    responses={"200": _ok("The account's access"), "401": _ERR, "403": _ERR, "404": _ERR},
)
register_api_path(
    "access-api-users",
    subpath="{user}/check/",
    methods=["GET"],
    summary="Whether the account holds a permission, and why",
    tags=_TAG,
    parameters=[_USER, {"name": "perm", "in": "query", "required": True, "schema": {"type": "string"}}],
    responses={"200": _ok("allowed, exists, reasons"), "400": _ERR, "401": _ERR, "403": _ERR, "404": _ERR},
)
register_api_path(
    "access-api-users",
    subpath="{user}/groups/{group}/",
    methods=["PUT", "DELETE"],
    summary="Add the account to a group (PUT) or remove it (DELETE); recorded as an access change",
    tags=_TAG,
    parameters=[_USER, _GROUP],
    responses={
        "200": _ok("username, group, member, changed"),
        "401": _ERR,
        "403": {**_ERR, "description": "Auth-level token and accounts.change_user required"},
        "404": _ERR,
    },
)
_PERM = {
    "name": "perm",
    "in": "path",
    "required": True,
    "schema": {"type": "string"},
    "description": "app_label.codename",
}
_NAME_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        }
    },
}
_WRITE_403 = {**_ERR, "description": "Auth-level token and the matching auth.*_group permission required"}
register_api_path(
    "access-api-users",
    subpath="{user}/permissions/{perm}/",
    methods=["DELETE"],
    summary="Take a direct permission off the account (grant through a group instead); recorded",
    tags=_TAG,
    parameters=[_USER, _PERM],
    responses={
        "200": _ok("username, permission, held, changed"),
        "401": _ERR,
        "403": {**_ERR, "description": "Auth-level token and accounts.change_user required"},
        "404": _ERR,
    },
)
register_api_path(
    "access-api-groups",
    methods=["GET"],
    summary="Groups with their permissions and drift against the code's declaration",
    tags=_TAG,
    responses={"200": _ok("Groups"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-groups",
    methods=["POST"],
    summary="Create a group; recorded as an access change",
    tags=_TAG,
    request_body=_NAME_BODY,
    responses={"201": _ok("The group"), "400": _ERR, "401": _ERR, "403": _WRITE_403},
)
register_api_path(
    "access-api-groups",
    subpath="{group}/",
    methods=["GET"],
    summary="One group: members, permissions, declaration",
    tags=_TAG,
    parameters=[_GROUP],
    responses={"200": _ok("The group"), "401": _ERR, "403": _ERR, "404": _ERR},
)
register_api_path(
    "access-api-groups",
    subpath="{group}/",
    methods=["PATCH"],
    summary="Rename the group (not one declared in code, nor a directory-managed one)",
    tags=_TAG,
    parameters=[_GROUP],
    request_body=_NAME_BODY,
    responses={"200": _ok("The group, with changed"), "400": _ERR, "401": _ERR, "403": _WRITE_403, "404": _ERR},
)
register_api_path(
    "access-api-groups",
    subpath="{group}/",
    methods=["DELETE"],
    summary="Delete the group; its members keep their accounts (not one declared in code)",
    tags=_TAG,
    parameters=[_GROUP],
    responses={"200": _ok("group, deleted"), "401": _ERR, "403": _WRITE_403, "404": _ERR},
)
register_api_path(
    "access-api-groups",
    subpath="{group}/permissions/{perm}/",
    methods=["PUT", "DELETE"],
    summary="Grant the permission to the group (PUT; you must hold it yourself) or take it away (DELETE)",
    tags=_TAG,
    parameters=[_GROUP, _PERM],
    responses={"200": _ok("group, permission, held, changed"), "401": _ERR, "403": _WRITE_403, "404": _ERR},
)
register_api_path(
    "access-api-findings",
    methods=["GET"],
    summary="The least-privilege findings: every finding with its rows",
    tags=_TAG,
    responses={"200": _ok("worst severity and the findings"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-reviews",
    methods=["GET"],
    summary="Periodic access reviews (attestations), newest first; ?status=open|signed",
    tags=_TAG,
    parameters=[{"name": "status", "in": "query", "schema": {"type": "string"}}, _LIMIT],
    responses={"200": _ok("Reviews with their summaries"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-reviews",
    subpath="{review_id}/",
    methods=["GET"],
    summary="One access review: the frozen roster, each decision, the signature",
    tags=_TAG,
    parameters=[{"name": "review_id", "in": "path", "required": True, "schema": {"type": "integer"}}],
    responses={"200": _ok("The review"), "401": _ERR, "403": _ERR, "404": _ERR},
)
register_api_path(
    "access-api-evidence",
    methods=["GET"],
    summary="The audit evidence pack for a period: every sheet as JSON, or ?format=zip for the bundle",
    tags=_TAG,
    parameters=[
        {"name": "from", "in": "query", "required": True, "schema": {"type": "string", "format": "date"}},
        {"name": "to", "in": "query", "required": True, "schema": {"type": "string", "format": "date"}},
        {"name": "scope", "in": "query", "schema": {"type": "string", "enum": ["privileged", "all"]}},
        {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["json", "zip"]}},
    ],
    responses={"200": _ok("The pack (JSON), or a ZIP"), "400": _ERR, "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-evidence-packs",
    methods=["GET"],
    summary="Stored evidence packs (built when a quarter closed, a review was signed, or on request), newest first",
    tags=_TAG,
    parameters=[{"name": "scope", "in": "query", "schema": {"type": "string", "enum": ["privileged", "all"]}}, _LIMIT],
    responses={"200": _ok("Packs with period, reason, size and SHA-256"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-evidence-packs",
    subpath="{pack_id}/",
    methods=["GET"],
    summary="One stored evidence pack: its metadata, or ?format=zip for the file as stored",
    tags=_TAG,
    parameters=[
        {"name": "pack_id", "in": "path", "required": True, "schema": {"type": "integer"}},
        {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["json", "zip"]}},
    ],
    responses={"200": _ok("The pack (JSON), or its ZIP"), "401": _ERR, "403": _ERR, "404": _ERR},
)
register_api_path(
    "access-api-review-cadence",
    methods=["GET"],
    summary="Where the periodic access review stands: last quarter signed/open/not reviewed, due date, the schedule",
    tags=_TAG,
    responses={"200": _ok("The cadence status"), "401": _ERR, "403": _ERR},
)
register_api_path(
    "access-api-events",
    methods=["GET"],
    summary="Access changes, newest first",
    tags=_TAG,
    parameters=[
        {"name": "who", "in": "query", "schema": {"type": "string"}},
        {"name": "kind", "in": "query", "schema": {"type": "string"}, "description": "A kind, or 'grants'."},
        _LIMIT,
    ],
    responses={"200": _ok("Events"), "401": _ERR, "403": _ERR},
)
