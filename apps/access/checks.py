"""The built-in least-privilege findings.

Each is a plain function returning a :class:`Finding`, registered with
:func:`register_check`; an app adds its own the same way in its
``access_checks.py``. They read what is, and say what to look at; none of
them changes anything.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import ManagedGroup
from .registry import Finding, register_check

User = get_user_model()


def _dormant_days() -> int:
    return int(getattr(settings, "SMALLSTACK_ACCESS_DORMANT_DAYS", 90))


def _user_row(user: Any, meta: str = "") -> dict[str, Any]:
    return {
        "label": user.get_username(),
        "href": reverse("access:user_detail", kwargs={"pk": user.pk}),
        "meta": meta or _last_login(user),
    }


def _group_row(group: Group, meta: str = "") -> dict[str, Any]:
    return {"label": group.name, "href": reverse("access:group_detail", kwargs={"pk": group.pk}), "meta": meta}


def _quiet_summary(qs: Any, who: str) -> str:
    """The all-clear for a dormancy check, without claiming that accounts
    which never signed in have (they're new, so not yet dormant)."""
    never = qs.filter(last_login__isnull=True).count()
    text = f"No {who} has gone {_dormant_days()} days without signing in"
    if never:
        text += f" ({never} {'has' if never == 1 else 'have'} never signed in, joined within that time)"
    return text + "."


def _last_login(user: Any) -> str:
    if user.last_login is None:
        return f"never signed in · joined {user.date_joined:%b %d, %Y}"
    return f"last sign-in {user.last_login:%b %d, %Y}"


@register_check
def superusers() -> Finding:
    users = list(User.objects.filter(is_active=True, is_superuser=True).order_by("username"))
    n = len(users)
    if n == 0:
        severity, summary = "warning", "No active superuser: keep one local break-glass administrator."
    elif n <= 2:
        severity, summary = "ok", f"{n} active superuser account{'s' if n != 1 else ''}."
    else:
        severity, summary = (
            "warning",
            f"{n} active superusers. A superuser bypasses every permission check; most staff need a group instead.",
        )
    return Finding(
        "superusers",
        "Superusers",
        severity,
        n,
        summary,
        [_user_row(u) for u in users],
        advice="Keep superuser for break-glass use. Give day-to-day administrators a group.",
    )


@register_check
def dormant_privileged() -> Finding:
    cutoff = timezone.now() - timedelta(days=_dormant_days())
    privileged = User.objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
    users = list(
        privileged.filter(Q(last_login__lt=cutoff) | Q(last_login__isnull=True, date_joined__lt=cutoff)).order_by(
            "username"
        )
    )
    n = len(users)
    severity = "danger" if any(u.is_superuser for u in users) else ("warning" if n else "ok")
    summary = (
        f"{n} privileged account{'s' if n != 1 else ''} with no sign-in for {_dormant_days()} days."
        if n
        else _quiet_summary(privileged, "staff or superuser account")
    )
    rows = [_user_row(u, ("superuser · " if u.is_superuser else "staff · ") + _last_login(u)) for u in users]
    return Finding(
        "dormant_privileged",
        "Dormant privileged accounts",
        severity,
        n,
        summary,
        rows,
        advice="Deactivate accounts that are no longer used; deactivation also revokes their tokens and sessions.",
    )


@register_check
def direct_permissions() -> Finding:
    users = list(User.objects.annotate(n=Count("user_permissions")).filter(n__gt=0).order_by("username"))
    n = len(users)
    return Finding(
        "direct_permissions",
        "Permissions granted directly",
        "warning" if n else "ok",
        n,
        f"{n} account{'s' if n != 1 else ''} hold permissions outside any group."
        if n
        else "Every permission is granted through a group.",
        [_user_row(u, f"{u.n} direct permission{'s' if u.n != 1 else ''}") for u in users],
        advice="Grant through groups, so a role can be reviewed and removed as one thing.",
    )


@register_check
def inactive_with_tokens() -> Finding:
    users = list(User.objects.filter(is_active=False, api_tokens__is_active=True).distinct().order_by("username"))
    n = len(users)
    return Finding(
        "inactive_with_tokens",
        "Deactivated accounts with live API tokens",
        "danger" if n else "ok",
        n,
        f"{n} deactivated account{'s' if n != 1 else ''} still hold an active API token."
        if n
        else "No deactivated account holds a live token.",
        [_user_row(u, "deactivated, token still active") for u in users],
        advice="Revoke the tokens on the user's Access page. Deactivating an account now revokes them automatically.",
    )


@register_check
def dormant_accounts() -> Finding:
    cutoff = timezone.now() - timedelta(days=_dormant_days())
    members = User.objects.filter(is_active=True, is_staff=False, is_superuser=False)
    users = list(
        members.filter(Q(last_login__lt=cutoff) | Q(last_login__isnull=True, date_joined__lt=cutoff)).order_by(
            "username"
        )
    )
    n = len(users)
    return Finding(
        "dormant_accounts",
        "Dormant accounts",
        "info" if n else "ok",
        n,
        f"{n} active account{'s' if n != 1 else ''} with no sign-in for {_dormant_days()} days."
        if n
        else _quiet_summary(members, "active account"),
        [_user_row(u) for u in users],
        advice="Deactivate what isn't used. An account that can't sign in can't be misused.",
    )


@register_check
def staff_without_groups() -> Finding:
    users = list(
        User.objects.filter(is_active=True, is_staff=True, is_superuser=False)
        .annotate(n=Count("groups"))
        .filter(n=0)
        .order_by("username")
    )
    n = len(users)
    return Finding(
        "staff_without_groups",
        "Staff with no group",
        "info" if n else "ok",
        n,
        f"{n} staff account{'s' if n != 1 else ''} rely on the staff flag alone."
        if n
        else "Every staff account belongs to a group.",
        [_user_row(u) for u in users],
        advice="The staff flag opens the admin area; a group says what they do there.",
    )


@register_check
def group_drift() -> Finding:
    rows = []
    for managed in ManagedGroup.objects.select_related("group"):
        drift = managed.drift()
        if drift["added"] or drift["missing"]:
            parts = []
            if drift["added"]:
                parts.append(f"{len(drift['added'])} added by hand")
            if drift["missing"]:
                parts.append(f"{len(drift['missing'])} declared but missing")
            rows.append(_group_row(managed.group, ", ".join(parts)))
    n = len(rows)
    return Finding(
        "group_drift",
        "Groups that differ from their declaration",
        "warning" if n else "ok",
        n,
        f"{n} group{'s' if n != 1 else ''} declared in code hold other permissions than declared."
        if n
        else "Every group declared in code matches its declaration.",
        rows,
        advice="Put the change in the app's groups.py, or remove it, so the code says what the group grants.",
    )


@register_check
def empty_groups() -> Finding:
    groups = list(
        Group.objects.annotate(m=Count("user", distinct=True), p=Count("permissions", distinct=True))
        .filter(Q(m=0) | Q(p=0))
        .order_by("name")
    )
    n = len(groups)
    rows = [_group_row(g, "no members" if g.m == 0 else "no permissions") for g in groups]
    return Finding(
        "empty_groups",
        "Groups with no members or no permissions",
        "info" if n else "ok",
        n,
        f"{n} group{'s' if n != 1 else ''} grant nothing or to no one."
        if n
        else "Every group has members and permissions.",
        rows,
        advice="Delete what isn't used, so the list of groups stays something a reviewer can read.",
    )


@register_check
def system_tokens() -> Finding:
    from apps.smallstack.models import APIToken

    from .services import CHANGE_MEMBERSHIP

    tokens = list(APIToken.objects.filter(is_active=True, access_level="auth").select_related("user").order_by("name"))
    n = len(tokens)

    def can_manage(user: Any) -> bool:
        # What the account endpoints ask of an auth-level token's owner.
        return bool(user.is_active and (user.is_staff or user.is_superuser) and user.has_perm(CHANGE_MEMBERSHIP))

    managing = {t.pk for t in tokens if can_manage(t.user)}
    rows = [
        {
            "label": t.name,
            "href": reverse("access:user_detail", kwargs={"pk": t.user.pk}),
            "meta": (f"{t.user.get_username()} · last used {t.last_used_at:%b %d, %Y}"
                     if t.last_used_at
                     else f"{t.user.get_username()} · never used")
            + (" · can manage accounts" if t.pk in managing else ""),
        }
        for t in tokens
    ]
    k = len(managing)
    return Finding(
        "system_tokens",
        "Auth-level API tokens",
        "info" if n else "ok",
        n,
        f"{n} active auth-level token{'s' if n != 1 else ''}; {k} can manage accounts over the API "
        "(the owner is staff holding accounts.change_user)."
        if n
        else "No auth-level tokens are active.",
        rows,
        advice="Each should belong to a known integration, with an expiry.",
    )
