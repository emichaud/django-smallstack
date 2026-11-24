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

from .models import AccessEvent, DirectoryIdentity, ManagedGroup
from .registry import Finding, declared_groups, register_check

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


# --- Directory-managed groups -----------------------------------------------------
# These read the sync's footprint (apps/access/directory.py): the groups with
# a directory role, the identities it has seen, the events it recorded.


def _directory_in_use() -> bool:
    return ManagedGroup.objects.filter(directory_role__isnull=False).exists()


@register_check
def directory_local_changes() -> Finding:
    """A directory-managed group's membership changed from somewhere other than
    the directory sync (Django admin, a shell): the next sign-in undoes it,
    and until then two places disagree about who is in the group."""
    cutoff = timezone.now() - timedelta(days=_dormant_days())
    events = list(
        AccessEvent.objects.filter(
            at__gte=cutoff,
            kind__in=[AccessEvent.Kind.GROUP_ADDED, AccessEvent.Kind.GROUP_REMOVED],
            group__managed__directory_role__isnull=False,
        )
        .exclude(source__startswith="directory:")
        .exclude(source="migrate")
        .select_related("group")
        .order_by("-at")[:200]
    )
    n = len(events)
    rows = [
        {
            "label": f"{e.subject_label} {'added to' if e.kind == AccessEvent.Kind.GROUP_ADDED else 'removed from'} "
            f"{e.group_label}",
            "href": reverse("access:group_detail", kwargs={"pk": e.group_id}) if e.group_id else "",
            "meta": f"{e.at:%b %d, %Y} · {e.actor_label or 'no actor'} · {e.source}",
        }
        for e in events
    ]
    return Finding(
        "directory_local_changes",
        "Directory-managed groups changed locally",
        "warning" if n else "ok",
        n,
        f"{n} membership change{'s' if n != 1 else ''} to directory-managed groups came from outside the directory "
        f"in the last {_dormant_days()} days."
        if n
        else "Every change to a directory-managed group came from the directory.",
        rows,
        advice="Membership of these groups belongs in the directory; the next sign-in sets it back. "
        "Change it there, and look at who made the local change.",
    )


@register_check
def directory_superuser() -> Finding:
    """Superuser granted with a directory source: the sync never does this, so
    a sign-in backend did, and a directory now hands out the one flag that
    bypasses every check."""
    events = list(
        AccessEvent.objects.filter(kind=AccessEvent.Kind.SUPERUSER_ON, source__startswith="directory:")
        .select_related("subject")
        .order_by("-at")[:100]
    )
    n = len(events)
    rows = [
        {
            "label": e.subject_label,
            "href": reverse("access:user_detail", kwargs={"pk": e.subject_id}) if e.subject_id else "",
            "meta": f"{e.at:%b %d, %Y} · {e.source}",
        }
        for e in events
    ]
    return Finding(
        "directory_superuser",
        "Superuser granted by a directory",
        "danger" if n else "ok",
        n,
        f"{n} superuser grant{'s' if n != 1 else ''} recorded from a directory source."
        if n
        else "No directory has granted superuser.",
        rows,
        advice="Give directory-managed administrators a group with the permissions they need. "
        "Superuser stays a local break-glass account.",
    )


@register_check
def directory_unknown_roles() -> Finding:
    """A role value the directory sends that no declared group carries: code
    deployed without the directory step, or the other way round."""
    known = set(ManagedGroup.objects.filter(directory_role__isnull=False).values_list("directory_role", flat=True))
    seen: dict[str, int] = {}
    for roles in DirectoryIdentity.objects.exclude(last_roles=[]).values_list("last_roles", flat=True):
        for role in roles or []:
            if role not in known:
                seen[role] = seen.get(role, 0) + 1
    n = len(seen)
    rows = [
        {
            "label": role,
            "href": reverse("access:groups"),
            "meta": f"sent for {count} account{'s' if count != 1 else ''}",
        }
        for role, count in sorted(seen.items())
    ]
    return Finding(
        "directory_unknown_roles",
        "Directory roles no group carries",
        "warning" if n else "ok",
        n,
        f"{n} role value{'s' if n != 1 else ''} the directory sends match no declared group; "
        "the accounts holding them get nothing for it."
        if n
        else "Every role the directory sends matches a declared group.",
        rows,
        advice="Declare the group with that directory_role (or add it to SMALLSTACK_DIRECTORY_ROLE_MAP), "
        "or remove the role from the directory.",
    )


@register_check
def directory_undeclared_groups() -> Finding:
    """With the directory in use, a group declared in code without a directory
    role is still managed by hand: fine, but worth knowing."""
    if not _directory_in_use():
        return Finding(
            "directory_undeclared_groups",
            "Groups without a directory role",
            "ok",
            0,
            "No group is directory-managed; membership is granted here.",
        )
    declared = {g.name for g in declared_groups()}
    groups = list(
        ManagedGroup.objects.filter(directory_role__isnull=True, group__name__in=declared)
        .select_related("group")
        .order_by("group__name")
    )
    n = len(groups)
    return Finding(
        "directory_undeclared_groups",
        "Groups without a directory role",
        "info" if n else "ok",
        n,
        f"{n} declared group{'s' if n != 1 else ''} still take{'s' if n == 1 else ''} members here, not from the "
        "directory."
        if n
        else "Every declared group is directory-managed.",
        [_group_row(m.group, m.app_label or "code") for m in groups],
        advice="Give it a directory_role (or map_directory_role) when the directory should own its membership.",
    )


@register_check
def directory_unseen_with_tokens() -> Finding:
    """The directory last vouched for the account a while ago and it still
    holds a live token: a leaver whose token keeps working."""
    cutoff = timezone.now() - timedelta(days=_dormant_days())
    identities = list(
        DirectoryIdentity.objects.filter(
            last_seen_at__lt=cutoff, user__is_active=True, user__api_tokens__is_active=True
        )
        .select_related("user")
        .distinct()
        .order_by("user__username")
    )
    n = len(identities)
    rows = [
        _user_row(i.user, f"{i.provider} last saw them {i.last_seen_at:%b %d, %Y} · live token") for i in identities
    ]
    return Finding(
        "directory_unseen_with_tokens",
        "Accounts the directory hasn't seen, with live tokens",
        "warning" if n else "ok",
        n,
        f"{n} account{'s' if n != 1 else ''} not signed in through the directory for {_dormant_days()} days still "
        "hold a live API token."
        if n
        else "Every account with a live token has signed in through the directory recently (or never used one).",
        rows,
        advice="Deactivate the account if they've left (that revokes the tokens), or revoke the tokens.",
    )


@register_check
def directory_password_beside_identity() -> Finding:
    """An account the directory signs in that also keeps a usable local
    password (T2-10): typically one linked by email from before single
    sign-on. The password is a second way in that disabling the person in the
    directory doesn't close. Kept on purpose for a break-glass administrator,
    who shouldn't have a directory identity at all."""
    identities = list(
        DirectoryIdentity.objects.filter(user__is_active=True).select_related("user").order_by("user__username")
    )
    users = {i.user.pk: i for i in identities if i.user.has_usable_password()}
    n = len(users)
    rows = [_user_row(i.user, f"signs in through {i.provider} · local password usable") for i in users.values()]
    return Finding(
        "directory_password_beside_identity",
        "Directory accounts with a local password",
        "warning" if n else "ok",
        n,
        f"{n} account{'s' if n != 1 else ''} the directory signs in also keep{'s' if n == 1 else ''} a usable local "
        "password, which still works if the directory disables them."
        if n
        else "No account the directory signs in has a usable local password.",
        rows,
        advice="Remove the local password (set an unusable one) once the account signs in through the directory.",
    )


# --- Access reviews (attestation) ---------------------------------------------------


@register_check
def review_overdue() -> Finding:
    """The last complete quarter has no signed review covering it: the
    control isn't operating. Two quarters without one is danger."""
    from . import cadence, reviews
    from .models import AccessReview

    quarters = reviews.recent_quarters(2)
    missing = [q for q in quarters if reviews.covered(q) is None]
    n = len(missing)
    open_by_period = {
        (r.period_start, r.period_end): r for r in AccessReview.objects.filter(status=AccessReview.Status.OPEN)
    }
    rows = []
    for q in missing:
        opened = open_by_period.get((q.start, q.end))
        due = q.end + timedelta(days=cadence.due_days())
        state = (
            f"open since {opened.opened_at:%b %d}, {reviews.live_counts(opened)['pending']} pending"
            if opened
            else "not opened"
        )
        href = reverse("access:review_detail", kwargs={"pk": opened.pk}) if opened else reverse("access:reviews")
        rows.append(
            {
                "label": q.label,
                "href": href,
                "meta": f"{q.start:%b %d} – {q.end:%b %d, %Y} · {state} · due {due:%b %d, %Y}",
            }
        )
    if n and not AccessReview.objects.filter(status=AccessReview.Status.SIGNED).exists():
        # Never reviewed: the control isn't in use yet, which is worth saying
        # without painting a new project red.
        return Finding(
            "review_overdue",
            "Access review overdue",
            "info",
            n,
            "No access review has been signed yet; nothing shows a person has looked at who holds access.",
            rows,
            advice="Open a review for the last quarter on the Reviews page, decide every account, and sign it.",
        )
    return Finding(
        "review_overdue",
        "Access review overdue",
        "danger" if n >= 2 else ("warning" if n else "ok"),
        n,
        f"{n} of the last 2 quarters {'has' if n == 1 else 'have'} no signed access review."
        if n
        else "The last two quarters each have a signed access review.",
        rows,
        advice="Open a review for the quarter on the Reviews page, decide every account, and sign it.",
    )


@register_check
def review_unresolved() -> Finding:
    """Rows of signed reviews still waiting on someone: flagged, or *remove*
    while the account is still active (its approval pending, rejected,
    canceled or expired)."""
    from . import reviews

    items = reviews.unresolved_items()
    n = len(items)
    rows = [
        {
            "label": i.user_label,
            "href": reverse("access:review_detail", kwargs={"pk": i.review_id}),
            "meta": f"{i.get_decision_display().lower()} in review #{i.review_id}"
            + (f" · {i.follow_up}" if i.follow_up else "")
            + (f" ({getattr(i, 'approval_state', '')})" if getattr(i, "approval_state", "") else ""),
        }
        for i in items
    ]
    return Finding(
        "review_unresolved",
        "Review decisions not yet acted on",
        "warning" if n else "ok",
        n,
        f"{n} account{'s' if n != 1 else ''} a signed review flagged or marked for removal still "
        f"wait{'s' if n == 1 else ''} on someone."
        if n
        else "Every decision of a signed review has been acted on.",
        rows,
        advice="Decide the pending approval; where it was rejected, canceled or expired, deactivate the account "
        "by hand or record why it stays in the next review. Look at a flagged account and deactivate or confirm it.",
    )


@register_check
def privileged_since_review() -> Finding:
    """Privileged accounts the last signed review didn't see: what the next
    review will find new."""
    from . import reviews
    from .models import AccessReview

    last = reviews.last_signed(AccessReview.Scope.PRIVILEGED) or reviews.last_signed(AccessReview.Scope.ALL)
    if last is None:
        return Finding(
            "privileged_since_review",
            "Privileged accounts not yet reviewed",
            "ok",
            0,
            "No review has been signed yet; the first one sees every account as new.",
        )
    seen = set(last.items.values_list("user_label", flat=True))
    users = [u for u in reviews.roster_users(AccessReview.Scope.PRIVILEGED) if u.get_username() not in seen]
    n = len(users)
    return Finding(
        "privileged_since_review",
        "Privileged accounts not yet reviewed",
        "info" if n else "ok",
        n,
        f"{n} privileged account{'s' if n != 1 else ''} appeared since review #{last.pk} was signed."
        if n
        else f"Every privileged account was on review #{last.pk}.",
        [_user_row(u, "not on the last signed review") for u in users],
        advice="They'll be marked new on the next review; nothing to do until then unless one surprises you.",
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
            "meta": (
                f"{t.user.get_username()} · last used {t.last_used_at:%b %d, %Y}"
                if t.last_used_at
                else f"{t.user.get_username()} · never used"
            )
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
