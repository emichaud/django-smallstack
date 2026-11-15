"""What a user can do, and why: the questions the Access pages answer.

Everything here reads Django's own permission data (superuser flag, groups,
direct permissions) and explains it; nothing decides access. ``user.has_perm``
remains the check every view, API and tool makes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone

from .context import acting_as
from .models import AccessEvent, ManagedGroup

User = get_user_model()

# The permission each write asks for, on every surface: what Django admin asks
# for the same edit. Superusers hold both.
CHANGE_MEMBERSHIP = "accounts.change_user"
REVOKE_TOKENS = "smallstack.change_apitoken"


def perm_name(perm: Permission) -> str:
    return f"{perm.content_type.app_label}.{perm.codename}"


@dataclass
class Grant:
    """One permission a user holds, and every route by which they hold it."""

    perm: str
    label: str
    app_label: str
    model: str
    sources: list[str] = field(default_factory=list)

    @property
    def via_group_only(self) -> bool:
        return bool(self.sources) and all(s.startswith("group:") for s in self.sources)


def effective_permissions(user: Any) -> list[Grant]:
    """Every permission ``user`` holds, with its sources: ``superuser``,
    ``group:<name>`` or ``direct``. Inactive users hold none (as ``has_perm``
    answers), but the list still shows what the account would hold if
    reactivated, marked by the caller."""
    grants: dict[str, Grant] = {}

    def add(perm: Permission, source: str) -> None:
        key = perm_name(perm)
        grant = grants.get(key)
        if grant is None:
            grant = Grant(
                perm=key,
                label=str(perm.name),
                app_label=perm.content_type.app_label,
                model=perm.content_type.model,
            )
            grants[key] = grant
        if source not in grant.sources:
            grant.sources.append(source)

    perms = Permission.objects.select_related("content_type").order_by(
        "content_type__app_label", "content_type__model", "codename"
    )
    if user.is_superuser:
        for perm in perms:
            add(perm, "superuser")
    for group in user.groups.prefetch_related(Prefetch("permissions", queryset=perms)).order_by("name"):
        for perm in group.permissions.all():
            add(perm, f"group:{group.name}")
    for perm in perms.filter(user=user):
        add(perm, "direct")
    return sorted(grants.values(), key=lambda g: (g.app_label, g.model, g.perm))


def grants_by_app(grants: Iterable[Grant]) -> list[tuple[str, list[Grant]]]:
    by_app: dict[str, list[Grant]] = {}
    for grant in grants:
        by_app.setdefault(grant.app_label, []).append(grant)
    return sorted(by_app.items())


@dataclass
class Explanation:
    perm: str
    allowed: bool
    reasons: list[str]
    exists: bool = True


def explain(user: Any, perm: str) -> Explanation:
    """Whether ``user.has_perm(perm)`` is true, and why."""
    perm = perm.strip()
    app, _, codename = perm.partition(".")
    exists = (
        bool(app and codename) and Permission.objects.filter(content_type__app_label=app, codename=codename).exists()
    )
    if not user.is_active:
        return Explanation(perm, False, ["The account is deactivated: an inactive user holds no permissions."], exists)
    if user.is_superuser:
        return Explanation(perm, user.has_perm(perm), ["Superuser: holds every permission."], exists)
    reasons = []
    for group in user.groups.filter(
        permissions__content_type__app_label=app, permissions__codename=codename
    ).distinct():
        reasons.append(f"Member of group {group.name!r}, which grants it.")
    if user.user_permissions.filter(content_type__app_label=app, codename=codename).exists():
        reasons.append("Granted directly on the account.")
    allowed = user.has_perm(perm)
    if not reasons:
        reasons.append("No group grants it and it isn't granted directly." if exists else "No such permission exists.")
    return Explanation(perm, allowed, reasons, exists)


def group_source_event(user: Any, group: Group) -> AccessEvent | None:
    """The event that last added ``user`` to ``group``: who did it, when, from where."""
    return (
        AccessEvent.objects.filter(subject=user, group=group, kind=AccessEvent.Kind.GROUP_ADDED).order_by("-at").first()
    )


# --- Tables -------------------------------------------------------------------


def users_with_access(qs: QuerySet[Any] | None = None) -> QuerySet[Any]:
    """Users annotated for the Access user list: group and direct-permission
    counts and active-token counts, prefetching groups."""
    base = User.objects.all() if qs is None else qs
    return (
        base.annotate(
            direct_permission_count=Count("user_permissions", distinct=True),
            active_token_count=Count("api_tokens", filter=Q(api_tokens__is_active=True), distinct=True),
        )
        .prefetch_related("groups")
        .order_by("username")
    )


def groups_with_counts() -> QuerySet[Any]:
    return (
        Group.objects.annotate(
            member_count=Count("user", distinct=True),
            permission_count=Count("permissions", distinct=True),
        )
        .select_related("managed")
        .order_by("name")
    )


def managed_for(group: Group) -> ManagedGroup | None:
    try:
        return group.managed  # type: ignore[attr-defined,no-any-return]  # the OneToOne's reverse accessor
    except ManagedGroup.DoesNotExist:
        return None


# --- Exports ------------------------------------------------------------------

MATRIX_COLUMNS = (
    "username",
    "email",
    "active",
    "staff",
    "superuser",
    "last_login",
    "permission",
    "permission_name",
    "source",
)


def access_matrix_rows() -> Iterator[dict[str, Any]]:
    """One row per (user, permission, source): the evidence an auditor asks
    for. A user with no permissions still appears once, so the file lists
    every account."""
    for user in User.objects.order_by("username").iterator():
        base = {
            "username": user.get_username(),
            "email": user.email or "",
            "active": user.is_active,
            "staff": user.is_staff,
            "superuser": user.is_superuser,
            "last_login": user.last_login.isoformat() if user.last_login else "",
        }
        grants = effective_permissions(user)
        if not grants:
            yield {**base, "permission": "", "permission_name": "", "source": ""}
            continue
        for grant in grants:
            for source in grant.sources:
                yield {**base, "permission": grant.perm, "permission_name": grant.label, "source": source}


def snapshot() -> dict[str, Any]:
    """The whole access picture as JSON: accounts, groups and findings, dated."""
    from .registry import run_checks

    users = []
    for user in users_with_access():
        users.append(
            {
                "username": user.get_username(),
                "email": user.email or "",
                "active": user.is_active,
                "staff": user.is_staff,
                "superuser": user.is_superuser,
                "last_login": user.last_login.isoformat() if user.last_login else None,
                "date_joined": user.date_joined.isoformat(),
                "groups": sorted(g.name for g in user.groups.all()),
                "direct_permissions": sorted(
                    perm_name(p) for p in user.user_permissions.select_related("content_type")
                ),
                "active_tokens": user.active_token_count,
            }
        )
    groups = []
    for group in groups_with_counts():
        managed = managed_for(group)
        groups.append(
            {
                "name": group.name,
                "members": sorted(group.user_set.values_list("username", flat=True)),
                "permissions": sorted(perm_name(p) for p in group.permissions.select_related("content_type")),
                "declared_in_code": managed is not None,
                "drift": managed.drift() if managed else None,
            }
        )
    return {
        "generated_at": timezone.now().isoformat(),
        "users": users,
        "groups": groups,
        "findings": [f.as_dict() for f in run_checks()],
    }


def user_access_summary(user: Any) -> dict[str, Any]:
    """The short version of the user's Access page, for a tab on another page
    (the User Manager): groups with when and by whom, counts, and the last
    few changes. The full page explains every permission."""
    groups = [{"group": g, "since": group_source_event(user, g)} for g in user.groups.order_by("name")]
    return {
        "groups": groups,
        "direct_permissions": [perm_name(p) for p in user.user_permissions.select_related("content_type")],
        "grant_count": len(effective_permissions(user)),
        "active_tokens": user.api_tokens.filter(is_active=True).count(),
        "events": list(
            AccessEvent.objects.filter(Q(subject=user) | Q(actor=user)).select_related("actor", "group")[:8]
        ),
    }


# --- Lookups ------------------------------------------------------------------


def resolve_user(ref: Any) -> Any:
    """A user by username, email or pk. Raises ``LookupError`` naming what
    was tried, so every surface reports a miss the same way."""
    text = str(ref or "").strip()
    if not text:
        raise LookupError("A username is required.")
    user = User.objects.filter(username=text).first()
    if user is None and "@" in text:
        user = User.objects.filter(email__iexact=text).first()
    if user is None and text.isdigit():
        user = User.objects.filter(pk=int(text)).first()
    if user is None:
        raise LookupError(f"No user {text!r}.")
    return user


def resolve_group(ref: Any) -> Group:
    """A group by name or pk."""
    text = str(ref or "").strip()
    if not text:
        raise LookupError("A group name is required.")
    group = Group.objects.filter(name=text).first()
    if group is None and text.isdigit():
        group = Group.objects.filter(pk=int(text)).first()
    if group is None:
        known = ", ".join(Group.objects.order_by("name").values_list("name", flat=True)) or "(none)"
        raise LookupError(f"No group {text!r}. Groups: {known}")
    return group


# --- The one write --------------------------------------------------------------


class MembershipRefused(PermissionError):
    """The actor may not make this membership change (→ 403 on every surface)."""


def permissions_actor_lacks(actor: Any, group: Group) -> list[str]:
    """The permissions ``group`` grants that ``actor`` doesn't hold, sorted.
    Empty for a superuser. Adding a member to a group hands them all of its
    permissions, so this is what an add would give away beyond the actor's own."""
    if getattr(actor, "is_superuser", False) and actor.is_active:
        return []
    held = actor.get_all_permissions() if actor.is_active else set()
    granted = {perm_name(p) for p in group.permissions.select_related("content_type")}
    return sorted(granted - held)


def set_membership(user: Any, group: Group, member: bool, *, actor: Any, source: str) -> bool:
    """Add ``user`` to ``group`` (``member=True``) or remove them. Every
    surface that changes membership calls this: the Access pages, REST, the
    approved MCP request and the CLI. Returns whether anything changed.

    The change is attributed to ``actor`` from ``source`` (``web:/…``,
    ``rest``, ``mcp:approval:<id>``, ``cli``), and the m2m signal records it
    as an :class:`AccessEvent`, a log line and a history entry. ``None`` is a
    local command. Otherwise, on every surface, ``actor`` must

    - be staff and hold :data:`CHANGE_MEMBERSHIP`, and
    - to *add* a member, hold every permission the group carries (see
      :func:`permissions_actor_lacks`), so a User manager can't hand out, or
      take, more than they have. Superusers hold everything; removal needs
      only the first rule.

    A refusal raises :class:`MembershipRefused` (a ``PermissionError``).
    """
    if actor is not None:
        if not (actor.is_active and (actor.is_staff or actor.is_superuser)):
            raise MembershipRefused(f"{actor.get_username()} is not staff; changing membership needs a staff account.")
        if not actor.has_perm(CHANGE_MEMBERSHIP):
            raise MembershipRefused(
                f"{actor.get_username()} lacks {CHANGE_MEMBERSHIP}, which changing membership needs."
            )
        if member:
            missing = permissions_actor_lacks(actor, group)
            if missing:
                shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
                raise MembershipRefused(
                    f"{actor.get_username()} can't add members to {group.name!r}: it grants "
                    f"{len(missing)} permission{'s' if len(missing) != 1 else ''} they don't hold ({shown}). "
                    "Only someone holding all of a group's permissions (or a superuser) may add to it."
                )
    is_member = user.groups.filter(pk=group.pk).exists()
    if is_member == member:
        return False
    with acting_as(actor, source):
        if member:
            user.groups.add(group)
        else:
            user.groups.remove(group)
    return True


# --- Wire payloads ----------------------------------------------------------------
# One shape for REST, MCP and ``manage.py access --json``: what the Access
# pages show, as JSON.


def _event_payload(event: AccessEvent) -> dict[str, Any]:
    return {
        "at": event.at.isoformat(),
        "kind": event.kind,
        "grant": event.is_grant,
        "actor": event.actor_label or None,
        "subject": event.subject_label or None,
        "group": event.group_label or None,
        "permission": event.permission or None,
        "source": event.source,
        "request_id": event.request_id,
        "detail": event.detail,
    }


def event_payloads(events: Iterable[AccessEvent]) -> list[dict[str, Any]]:
    return [_event_payload(e) for e in events]


def explanation_payload(user: Any, perm: str) -> dict[str, Any]:
    answer = explain(user, perm)
    return {
        "username": user.get_username(),
        "permission": answer.perm,
        "allowed": answer.allowed,
        "exists": answer.exists,
        "reasons": answer.reasons,
    }


def user_payload(user: Any, *, events: int = 10) -> dict[str, Any]:
    """Everything the user's Access page shows: flags, groups with when and by
    whom, direct permissions, every effective permission with its sources,
    live tokens and the last few changes."""
    groups = []
    for group in user.groups.order_by("name"):
        since = group_source_event(user, group)
        groups.append(
            {
                "name": group.name,
                "since": since.at.isoformat() if since else None,
                "added_by": (since.actor_label or None) if since else None,
                "source": since.source if since else None,
            }
        )
    grants = effective_permissions(user)
    return {
        "username": user.get_username(),
        "email": user.email or "",
        "active": user.is_active,
        "staff": user.is_staff,
        "superuser": user.is_superuser,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "date_joined": user.date_joined.isoformat(),
        "groups": groups,
        "direct_permissions": sorted(perm_name(p) for p in user.user_permissions.select_related("content_type")),
        "permissions": [
            {"permission": g.perm, "name": g.label, "app": g.app_label, "sources": list(g.sources)} for g in grants
        ],
        "permission_count": len(grants),
        "active_tokens": user.api_tokens.filter(is_active=True).count(),
        "events": event_payloads(
            AccessEvent.objects.filter(Q(subject=user) | Q(actor=user)).select_related("actor", "group")[:events]
        ),
    }


def group_payload(group: Group, *, members: bool = True) -> dict[str, Any]:
    managed = managed_for(group)
    data: dict[str, Any] = {
        "name": group.name,
        "declared_in_code": managed is not None,
        "description": managed.description if managed else "",
        "app": managed.app_label if managed else "",
        "drift": managed.drift() if managed else None,
        "permissions": sorted(perm_name(p) for p in group.permissions.select_related("content_type")),
        "member_count": group.user_set.count(),
    }
    if members:
        data["members"] = list(group.user_set.order_by("username").values_list("username", flat=True))
    return data
