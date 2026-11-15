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
    GET    api/access/groups/                     groups, with drift against the code
    GET    api/access/groups/{group}/             one group: members, permissions
    GET    api/access/findings/                   the least-privilege review
    GET    api/access/events/?who=&kind=&limit=   the change log

``{user}`` is a username, email or id; ``{group}`` a name or id. Reads need a
staff account holding ``accounts.view_user`` (any token tier; superusers
pass); the write needs an auth-level token *and*
``accounts.change_user``, the bar the account endpoints set.
"""

from __future__ import annotations

from typing import Any, Union

from django.http import HttpRequest, JsonResponse

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


# --- Groups ---------------------------------------------------------------------


@api_view(methods=["GET"], require_staff=True)
def api_groups(request: HttpRequest) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    return {"results": [services.group_payload(g, members=False) for g in services.groups_with_counts()]}


@api_view(methods=["GET"], require_staff=True)
def api_group(request: HttpRequest, group: str) -> ApiResult:
    refused = _read_refusal(request)
    if refused:
        return refused
    try:
        grp = services.resolve_group(group)
    except LookupError as exc:
        return api_error(str(exc), 404)
    return services.group_payload(grp)


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
    or permission, ``?kind=`` one kind or ``grants``."""
    refused = _read_refusal(request)
    if refused:
        return refused
    from .views import _events_queryset

    qs = _events_queryset(request)
    return {"count": qs.count(), "results": services.event_payloads(qs[: _limit(request)])}


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
register_api_path(
    "access-api-groups",
    methods=["GET"],
    summary="Groups with their permissions and drift against the code's declaration",
    tags=_TAG,
    responses={"200": _ok("Groups"), "401": _ERR, "403": _ERR},
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
    "access-api-findings",
    methods=["GET"],
    summary="The least-privilege review: every finding with its rows",
    tags=_TAG,
    responses={"200": _ok("worst severity and the findings"), "401": _ERR, "403": _ERR},
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
