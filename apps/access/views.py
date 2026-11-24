"""The Access pages at /smallstack/access/: who may do what, why, and every change.

Reading needs a staff account holding ``accounts.view_user`` (what Django
admin and Explorer ask to list accounts; the *Access reviewer* and *User
manager* groups grant it). Changing a membership needs ``accounts.change_user``
(what Django admin asks for the same edit); revoking a token needs
``smallstack.change_apitoken``. Superusers hold all three.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseBase,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.mixins import StaffRequiredMixin, staff_required
from apps.smallstack.models import APIToken
from apps.smallstack.pagination import paginate_queryset
from apps.smallstack.redaction import redact_path
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from . import reviews, services
from .models import AccessEvent, EvidenceBundle, ManagedGroup
from .registry import Finding, declared_groups, run_checks
from .services import CHANGE_MEMBERSHIP, READ_ACCESS_REFUSAL, can_read_access
from .signals import revoke_access

User = get_user_model()


def can_change(user: Any) -> bool:
    return bool(user.has_perm(CHANGE_MEMBERSHIP))


def access_reader_required(view_func: Any) -> Any:
    """:func:`staff_required`, then ``accounts.view_user`` (superusers pass):
    the read bar for the function views here."""
    from functools import wraps

    from django.contrib.auth.views import redirect_to_login

    @wraps(view_func)
    def _signed_in(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        # A shared export link opened while signed out goes to sign-in and
        # back, as the pages do, rather than a bare 403 (G-2).
        if not request.user.is_authenticated and request.method in ("GET", "HEAD"):
            return redirect_to_login(request.get_full_path())
        return _wrapped(request, *args, **kwargs)

    @staff_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not can_read_access(request.user):
            raise PermissionDenied(READ_ACCESS_REFUSAL)
        return view_func(request, *args, **kwargs)

    return _signed_in


class AccessPageView(StaffRequiredMixin, TemplateView):
    page_size = 50

    def test_func(self) -> bool:
        return can_read_access(self.request.user)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["can_change"] = can_change(self.request.user)
        return context


# --- Overview -----------------------------------------------------------------


class IndexView(AccessPageView):
    template_name = "access/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        findings = run_checks()
        users = User.objects.filter(is_active=True)
        context.update(
            {
                "findings": findings,
                "attention": [f for f in findings if f.severity in ("danger", "warning")],
                "stats": {
                    "users": users.count(),
                    "staff": users.filter(is_staff=True).count(),
                    "superusers": users.filter(is_superuser=True).count(),
                    "groups": Group.objects.count(),
                    "grants_7d": AccessEvent.objects.filter(
                        at__gte=timezone.now() - timedelta(days=7), kind__in=AccessEvent.GRANTS
                    ).count(),
                },
                "recent_events": AccessEvent.objects.select_related("actor", "subject", "group")[:12],
            }
        )
        return context


@access_reader_required
def finding_detail(request: HttpRequest, key: str) -> HttpResponse:
    """The rows behind one finding, for the stat modal."""
    finding: Finding | None = next((f for f in run_checks() if f.key == key), None)
    if finding is None:
        raise Http404
    rows = [stat_list_row(r["label"], href=r.get("href"), meta=r.get("meta")) for r in finding.rows]
    return render_stat_list(rows, empty=finding.summary)


@access_reader_required
def stat_detail(request: HttpRequest, stat: str) -> HttpResponse:
    users = User.objects.filter(is_active=True).order_by("username")
    if stat == "staff":
        users = users.filter(is_staff=True)
    elif stat == "superusers":
        users = users.filter(is_superuser=True)
    elif stat == "groups":
        rows = [
            stat_list_row(
                g.name,
                href=reverse("access:group_detail", kwargs={"pk": g.pk}),
                meta=f"{g.permission_count} permission{'s' if g.permission_count != 1 else ''}",
                count=g.member_count,
            )
            for g in services.groups_with_counts()
        ]
        return render_stat_list(rows, empty="No groups yet.")
    elif stat != "users":
        raise Http404
    rows = [
        stat_list_row(
            u.get_username(),
            href=reverse("access:user_detail", kwargs={"pk": u.pk}),
            meta="superuser" if u.is_superuser else ("staff" if u.is_staff else ""),
        )
        for u in users
    ]
    return render_stat_list(rows, empty="No accounts.")


# --- Groups -------------------------------------------------------------------


class GroupsView(AccessPageView):
    template_name = "access/groups.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["crumbs"] = [("Groups", "")]
        context["can_add"] = not services.group_refusal(self.request.user, action="create")
        groups = list(services.groups_with_counts())
        managed = {m.group_id: m for m in ManagedGroup.objects.all()}
        declared = {g.name for g in declared_groups()}
        context["groups"] = [
            {
                "group": g,
                "managed": managed.get(g.pk),
                "declared": g.name in declared,
                "drift": managed[g.pk].drift() if g.pk in managed else None,
            }
            for g in groups
        ]
        return context


@require_POST
@staff_required
def group_create(request: HttpRequest) -> HttpResponse:
    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    try:
        group = services.create_group(
            request.POST.get("name", ""), actor=request.user, source=f"web:{redact_path(request.path)}"
        )
    except services.GroupRefused as exc:
        messages.error(request, str(exc))
        return redirect("access:groups")
    messages.success(request, f"Group {group.name} created. Give it permissions, then members.")
    return redirect("access:group_detail", pk=group.pk)


def _permissions_context(request: HttpRequest, group: Group) -> dict[str, Any]:
    """The Permissions card: what the group grants, by app, and what the
    viewer may add. Shared by the page and the htmx swap after a change."""
    managed = services.managed_for(group)
    declared = set(managed.declared_permissions or []) if managed else set()
    perms = group.permissions.select_related("content_type").order_by(
        "content_type__app_label", "content_type__model", "codename"
    )
    by_app: dict[str, list[dict[str, Any]]] = {}
    held: set[str] = set()
    for perm in perms:
        name = services.perm_name(perm)
        held.add(name)
        by_app.setdefault(perm.content_type.app_label, []).append(
            {
                "perm": name,
                "label": perm.name,
                "declared": name in declared,
                "added": bool(managed) and name not in declared,
            }
        )
    can_manage = not services.group_refusal(request.user, group, action="permissions")
    available: dict[str, list[tuple[str, str]]] = {}
    if can_manage:
        # Only what the viewer may hand out: their own permissions, or everything for a superuser.
        for perm in Permission.objects.select_related("content_type").order_by(
            "content_type__app_label", "content_type__model", "codename"
        ):
            name = services.perm_name(perm)
            if name in held or not (request.user.is_superuser or request.user.has_perm(name)):
                continue
            available.setdefault(perm.content_type.app_label, []).append((name, perm.name))
    return {
        "group": group,
        "managed": managed,
        "declared_in_code": services.declared_in_code(group),
        "permissions_by_app": sorted(by_app.items()),
        "permission_count": len(held),
        "can_manage": can_manage,
        "available_permissions": sorted(available.items()),
    }


class GroupDetailView(AccessPageView):
    template_name = "access/group_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        group = get_object_or_404(Group, pk=self.kwargs["pk"])
        context.update(_permissions_context(self.request, group))
        managed = context["managed"]
        members = list(group.user_set.order_by("username"))
        source_by_user = {}
        for event in AccessEvent.objects.filter(
            group=group, kind=AccessEvent.Kind.GROUP_ADDED, subject__in=members
        ).order_by("at"):
            source_by_user[event.subject_id] = event  # the latest wins
        directory_refusal = services.directory_refusal(group)
        context.update(
            {
                "crumbs": [("Groups", reverse("access:groups")), (group.name, "")],
                "drift": managed.drift() if managed else None,
                # Membership set by the directory: the forms go, the banner says where.
                "directory_refusal": directory_refusal,
                "can_change": context.get("can_change") and not directory_refusal,
                "can_rename": not services.group_refusal(self.request.user, group, action="rename"),
                "can_delete": not services.group_refusal(self.request.user, group, action="delete"),
                "members": [{"user": u, "since": source_by_user.get(u.pk)} for u in members],
                "candidates": User.objects.filter(is_active=True)
                .exclude(pk__in=[u.pk for u in members])
                .order_by("username")[:500],
                "events": AccessEvent.objects.filter(group=group).select_related("actor", "subject")[:50],
            }
        )
        return context


@require_POST
@staff_required
def group_members(request: HttpRequest, pk: int) -> HttpResponse:
    """Add or remove one member. The m2m signal records the event."""
    if not can_change(request.user):
        raise PermissionDenied("You need the change_user permission to change group membership.")
    group = get_object_or_404(Group, pk=pk)
    user = get_object_or_404(User, pk=_posted_pk(request, "user"))
    # Where to go afterwards is settled before anything changes: only a
    # same-site path, so the form can't be turned into an open redirect.
    next_url = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = reverse("access:group_detail", kwargs={"pk": pk})
    if not _apply_membership(request, user, group):
        return HttpResponse("Unknown action.", status=400)
    return redirect(next_url)


@require_POST
@staff_required
def group_permissions(request: HttpRequest, pk: int) -> HttpResponse:
    """Grant or take one permission. An htmx request gets the Permissions
    card back (with the messages); a plain post goes back to the page."""
    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    group = get_object_or_404(Group, pk=pk)
    action = request.POST.get("action")
    perm = request.POST.get("perm", "").strip()
    if action not in ("add", "remove"):
        return HttpResponse("Unknown action.", status=400)
    try:
        changed = services.set_group_permission(
            group, perm, action == "add", actor=request.user, source=f"web:{redact_path(request.path)}"
        )
    except services.GroupRefused as exc:
        messages.error(request, str(exc))
    else:
        if changed:
            messages.success(request, f"{perm} {'added to' if action == 'add' else 'removed from'} {group.name}.")
        else:
            messages.info(request, f"{group.name} already {'had' if action == 'add' else 'lacked'} {perm}.")
    if getattr(request, "htmx", False):
        return render(request, "access/partials/group_permissions.html", _permissions_context(request, group))
    return redirect("access:group_detail", pk=pk)


@require_POST
@staff_required
def group_settings(request: HttpRequest, pk: int) -> HttpResponse:
    """Rename or delete the group."""
    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    group = get_object_or_404(Group, pk=pk)
    action = request.POST.get("action")
    source = f"web:{redact_path(request.path)}"
    try:
        if action == "rename":
            before = group.name
            if services.rename_group(group, request.POST.get("name", ""), actor=request.user, source=source):
                messages.success(request, f"{before} renamed to {group.name}.")
        elif action == "delete":
            name = group.name
            services.delete_group(group, actor=request.user, source=source)
            messages.success(request, f"Group {name} deleted; its members keep their accounts.")
            return redirect("access:groups")
        else:
            return HttpResponse("Unknown action.", status=400)
    except services.GroupRefused as exc:
        messages.error(request, str(exc))
    return redirect("access:group_detail", pk=pk)


def _posted_pk(request: HttpRequest, name: str) -> int:
    """A primary key from the POST body, or 404 for anything that isn't one
    (``abc``, ``²``) rather than a 500 from the lookup."""
    value = str(request.POST.get(name) or "")
    if not (value.isascii() and value.isdigit()):
        raise Http404(f"No such {name}.")
    return int(value)


def _apply_membership(request: HttpRequest, user: Any, group: Group) -> bool:
    """The add/remove form on either page, through the one membership service.
    Returns False for an unknown action."""
    action = request.POST.get("action")
    if action not in ("add", "remove"):
        return False
    try:
        changed = services.set_membership(
            user, group, action == "add", actor=request.user, source=f"web:{redact_path(request.path)}"
        )
    except services.MembershipRefused as exc:
        messages.error(request, str(exc))
        return True
    name = user.get_username()
    if changed:
        messages.success(request, f"{name} {'added to' if action == 'add' else 'removed from'} {group.name}.")
    else:
        messages.info(
            request, f"{name} was already {'in' if action == 'add' else 'out of'} {group.name}; nothing changed."
        )
    return True


# --- Users --------------------------------------------------------------------


#: The user list's columns: key → (label, order-by fields, numeric). A click on
#: the header sorts by the key; ``-key`` reverses.
USER_COLUMNS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "username": ("Account", ("username",), False),
    "role": ("Role", ("-is_superuser", "-is_staff", "username"), False),
    "groups": ("Groups", ("group_count", "username"), False),
    "direct": ("Direct", ("direct_permission_count", "username"), True),
    "tokens": ("Tokens", ("active_token_count", "username"), True),
    "last_login": ("Last sign-in", ("last_login", "username"), False),
    "date_joined": ("Joined", ("date_joined", "username"), False),
}
#: The filter pills, in order: key → (label, filter).
USER_FILTERS: dict[str, tuple[str, Q]] = {
    "active": ("Active", Q(is_active=True)),
    "staff": ("Staff", Q(is_active=True) & (Q(is_staff=True) | Q(is_superuser=True))),
    "inactive": ("Deactivated", Q(is_active=False)),
    "all": ("All", Q()),
}


class UsersView(AccessPageView):
    template_name = "access/users.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from django.db.models import Count, F

        from apps.smallstack.pagination import PAGE_SIZE_CHOICES, page_size_from
        from apps.smallstack.sorting import build_sort_headers

        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        show = self.request.GET.get("show", "active")
        if show not in USER_FILTERS:
            show = "active"
        ordering = self.request.GET.get("ordering", "username")
        key, desc = ordering.lstrip("-"), ordering.startswith("-")
        if key not in USER_COLUMNS:
            key, desc, ordering = "username", False, "username"
        base = services.users_with_access().annotate(group_count=Count("groups", distinct=True))
        qs = base.filter(USER_FILTERS[show][1])
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(groups__name__icontains=q)
            ).distinct()
        fields = USER_COLUMNS[key][1]
        if desc:
            # Reverse every field of the sort; nulls (never signed in) stay last either way.
            fields = tuple(f[1:] if f.startswith("-") else f"-{f}" for f in fields)
        order = [
            F(f.lstrip("-")).desc(nulls_last=True) if f.startswith("-") else F(f).asc(nulls_last=True) for f in fields
        ]
        qs = qs.order_by(*order)
        per_page = page_size_from(self.request, PAGE_SIZE_CHOICES)
        page = paginate_queryset(qs, self.request, page_size=per_page)
        # The filter pills carry a count each: a one-glance census of who holds access.
        counts = {k: base.filter(f).count() for k, (_label, f) in USER_FILTERS.items()}
        headers = build_sort_headers([(k, label) for k, (label, _f, _n) in USER_COLUMNS.items()], ordering)
        for h in headers:
            h["numeric"] = USER_COLUMNS[h["key"]][2]
        context.update(
            {
                "crumbs": [("Users", "")],
                "page_obj": page,
                "users": page.object_list,
                "q": q,
                "show": show,
                "filters": [(k, label, counts[k]) for k, (label, _f) in USER_FILTERS.items()],
                "headers": headers,
                "ordering": ordering,
                "page_sizes": PAGE_SIZE_CHOICES,
                "per_page": per_page,
            }
        )
        return context


class UserDetailView(AccessPageView):
    template_name = "access/user_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        grants = services.effective_permissions(user)
        groups = list(user.groups.select_related("managed").order_by("name"))
        perm = self.request.GET.get("perm", "").strip()
        context.update(
            {
                "crumbs": [("Users", reverse("access:users")), (user.get_username(), "")],
                "target": user,
                "groups": [
                    {
                        "group": g,
                        "since": services.group_source_event(user, g),
                        "directory": bool(services.directory_refusal(g)),
                    }
                    for g in groups
                ],
                # A directory-managed group can't be joined here; it isn't offered.
                "other_groups": [
                    g
                    for g in Group.objects.exclude(pk__in=[g.pk for g in groups])
                    .select_related("managed")
                    .order_by("name")
                    if not services.directory_refusal(g)
                ],
                "identities": list(user.directory_identities.order_by("provider")),
                "direct_permissions": [
                    services.perm_name(p) for p in user.user_permissions.select_related("content_type")
                ],
                "grants_by_app": services.grants_by_app(grants),
                "grant_count": len(grants),
                "tokens": APIToken.objects.filter(user=user).order_by("-is_active", "-created_at"),
                "live_token_count": APIToken.objects.filter(user=user, is_active=True).count(),
                "events": AccessEvent.objects.filter(Q(subject=user) | Q(actor=user)).select_related(
                    "actor", "subject", "group"
                )[:50],
                "check": services.explain(user, perm) if perm else None,
                "perm": perm,
                "can_revoke": not services.revoke_all_refusal(self.request.user, user),
                "can_remove_direct": not services.direct_permission_refusal(self.request.user, user),
            }
        )
        return context


@require_POST
@staff_required
def user_permissions(request: HttpRequest, pk: int) -> HttpResponse:
    """Take a direct permission off the account (there is no add: use a group)."""
    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    user = get_object_or_404(User, pk=pk)
    perm = request.POST.get("perm", "").strip()
    if request.POST.get("action") != "remove":
        return HttpResponse("Unknown action.", status=400)
    try:
        changed = services.remove_direct_permission(
            user, perm, actor=request.user, source=f"web:{redact_path(request.path)}"
        )
    except services.GroupRefused as exc:
        messages.error(request, str(exc))
    else:
        if changed:
            messages.success(request, f"Direct permission {perm} removed from {user.get_username()}.")
        else:
            messages.info(request, f"{user.get_username()} didn't hold {perm} directly.")
    return redirect(f"{reverse('access:user_detail', kwargs={'pk': pk})}#permissions")


@require_POST
@staff_required
def user_groups(request: HttpRequest, pk: int) -> HttpResponse:
    if not can_change(request.user):
        raise PermissionDenied("You need the change_user permission to change group membership.")
    user = get_object_or_404(User, pk=pk)
    group = get_object_or_404(Group, pk=_posted_pk(request, "group"))
    if not _apply_membership(request, user, group):
        return HttpResponse("Unknown action.", status=400)
    return redirect("access:user_detail", pk=pk)


@require_POST
@staff_required
def user_revoke(request: HttpRequest, pk: int) -> HttpResponse:
    """Revoke every live token and end every session of an account.
    ``services.revoke_all_refusal`` decides, as it does for the button."""
    user = get_object_or_404(User, pk=pk)
    refusal = services.revoke_all_refusal(request.user, user)
    if refusal:
        raise PermissionDenied(refusal)
    counts = revoke_access(user)
    messages.success(
        request,
        f"Revoked {counts['tokens']} token(s) and ended {counts['sessions']} session(s) for {user.get_username()}.",
    )
    return redirect("access:user_detail", pk=pk)


# --- Events -------------------------------------------------------------------


_K = AccessEvent.Kind
#: The change log's filter pills: ``?kind=<family>`` (a single kind still
#: works, for a link from a finding or a script). The CSV export and the REST
#: read take the same values.
EVENT_FAMILIES: dict[str, tuple[str, frozenset[str]]] = {
    "grants": ("Grants", AccessEvent.GRANTS),
    "removals": (
        "Removals",
        frozenset(
            {
                _K.GROUP_REMOVED,
                _K.PERMISSION_REMOVED,
                _K.GROUP_PERMISSION_REMOVED,
                _K.STAFF_OFF,
                _K.SUPERUSER_OFF,
                _K.DEACTIVATED,
            }
        ),
    ),
    "accounts": ("Accounts", frozenset({_K.USER_CREATED, _K.USER_DELETED, _K.ACTIVATED, _K.DEACTIVATED})),
    "groups": (
        "Groups",
        frozenset(
            {
                _K.GROUP_CREATED,
                _K.GROUP_DELETED,
                _K.GROUP_RENAMED,
                _K.GROUP_PERMISSION_ADDED,
                _K.GROUP_PERMISSION_REMOVED,
            }
        ),
    ),
    "credentials": ("Tokens & sessions", frozenset({_K.TOKEN_REVOKED, _K.SESSIONS_ENDED})),
    "reviews": ("Reviews", frozenset({_K.REVIEW_SIGNED})),
}
#: The change log's columns: key → (label, order-by fields). Default ``-at``.
EVENT_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "at": ("When", ("at", "pk")),
    "kind": ("Change", ("kind", "-at")),
    "subject": ("Account", ("subject_label", "-at")),
    "what": ("Group / permission", ("group_label", "permission", "-at")),
    "actor": ("By", ("actor_label", "-at")),
    "source": ("From", ("source", "-at")),
}


def _ordering(
    request: HttpRequest, columns: dict[str, tuple[str, tuple[str, ...]]], default: str
) -> tuple[str, list[Any]]:
    """``?ordering=`` as (the value kept in the address, the ORM order), falling
    back to ``default`` for a key that isn't a column. ``-key`` reverses every
    field of the column's sort; nulls stay last either way."""
    from django.db.models import F

    ordering = request.GET.get("ordering", default)
    key, desc = ordering.lstrip("-"), ordering.startswith("-")
    if key not in columns:
        ordering, key, desc = default, default.lstrip("-"), default.startswith("-")
    fields = columns[key][1]
    if desc:
        fields = tuple(f[1:] if f.startswith("-") else f"-{f}" for f in fields)
    order = [F(f.lstrip("-")).desc(nulls_last=True) if f.startswith("-") else F(f).asc(nulls_last=True) for f in fields]
    return ordering, order


def _events_queryset(request: HttpRequest) -> Any:
    qs = AccessEvent.objects.select_related("actor", "subject", "group")
    who = request.GET.get("who", "").strip()
    kind = request.GET.get("kind", "").strip()
    if who:
        qs = qs.filter(
            Q(subject_label__icontains=who)
            | Q(actor_label__icontains=who)
            | Q(group_label__icontains=who)
            | Q(permission__icontains=who)
        )
    if kind in EVENT_FAMILIES:
        qs = qs.filter(kind__in=EVENT_FAMILIES[kind][1])
    elif kind:
        qs = qs.filter(kind=kind)
    return qs.order_by(*_ordering(request, EVENT_COLUMNS, "-at")[1])


class EventsView(AccessPageView):
    template_name = "access/events.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack.pagination import PAGE_SIZE_CHOICES, page_size_from
        from apps.smallstack.sorting import build_sort_headers

        context = super().get_context_data(**kwargs)
        qs = _events_queryset(self.request)
        per_page = page_size_from(self.request, PAGE_SIZE_CHOICES)
        page = paginate_queryset(qs, self.request, page_size=per_page)
        ordering, _order = _ordering(self.request, EVENT_COLUMNS, "-at")
        kind = self.request.GET.get("kind", "")
        context.update(
            {
                "crumbs": [("Changes", "")],
                "page_obj": page,
                "events": page.object_list,
                "who": self.request.GET.get("who", ""),
                "kind": kind,
                # A pill per family; a single kind (from a link) shows as its own pill so the filter is visible.
                "families": [("", "All")]
                + [(k, label) for k, (label, _kinds) in EVENT_FAMILIES.items()]
                + (
                    [(kind, dict(AccessEvent.Kind.choices).get(kind, kind))]
                    if kind and kind not in EVENT_FAMILIES
                    else []
                ),
                "headers": build_sort_headers([(k, label) for k, (label, _f) in EVENT_COLUMNS.items()], ordering),
                "ordering": ordering,
                "page_sizes": PAGE_SIZE_CHOICES,
                "per_page": per_page,
                "querystring": self.request.GET.urlencode(),
            }
        )
        return context


class _Echo:
    def write(self, value: str) -> str:
        return value


#: A cell starting with one of these is a formula to a spreadsheet.
_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: Any) -> Any:
    """Neutralise a cell a spreadsheet would run as a formula (usernames may
    start with ``+ - @``; group names and emails are free text): prefix ``'``."""
    if isinstance(value, str) and value.startswith(_FORMULA_LEADS):
        return "'" + value
    return value


def _csv_response(filename: str, header: list[str], rows: Any) -> StreamingHttpResponse:
    writer = csv.DictWriter(_Echo(), fieldnames=header, extrasaction="ignore")

    def lines() -> Any:
        yield writer.writeheader()
        for row in rows:
            yield writer.writerow({key: _safe_cell(value) for key, value in row.items()})

    response = StreamingHttpResponse(lines(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@access_reader_required
def events_csv(request: HttpRequest) -> HttpResponseBase:
    header = ["at", "kind", "actor", "subject", "group", "permission", "source", "request_id", "detail"]
    rows = (
        {
            "at": e.at.isoformat(),
            "kind": e.kind,
            "actor": e.actor_label or "system",
            "subject": e.subject_label,
            "group": e.group_label,
            "permission": e.permission,
            "source": e.source,
            "request_id": e.request_id,
            "detail": json.dumps(e.detail, sort_keys=True) if e.detail else "",
        }
        for e in _events_queryset(request).iterator()
    )
    return _csv_response(f"access-events-{timezone.now():%Y%m%d}.csv", header, rows)


@access_reader_required
def matrix_csv(request: HttpRequest) -> HttpResponseBase:
    return _csv_response(
        f"access-matrix-{timezone.now():%Y%m%d}.csv", list(services.MATRIX_COLUMNS), services.access_matrix_rows()
    )


@access_reader_required
def snapshot_json(request: HttpRequest) -> HttpResponse:
    response = JsonResponse(services.snapshot(), json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="access-snapshot-{timezone.now():%Y%m%d}.json"'
    return response


# --- Reviews (attestation) ----------------------------------------------------------
# A review is opened on purpose, freezes the roster, and is signed by an
# attester; see apps/access/reviews.py. The pages call that module for every
# write; they decide nothing themselves.


def _review_or_404(pk: int) -> Any:
    from .models import AccessReview

    return get_object_or_404(AccessReview, pk=pk)


def _parse_period(request: HttpRequest) -> tuple[Any, Any]:
    """The period from the form: a quarter key (``start_end``) or two dates."""
    from datetime import date

    key = request.POST.get("period", "")
    if key == "custom":
        try:
            return date.fromisoformat(request.POST.get("start", "")), date.fromisoformat(request.POST.get("end", ""))
        except ValueError as exc:
            raise reviews.ReviewRefused("Give the period as two dates (YYYY-MM-DD).") from exc
    try:
        start, _, end = key.partition("_")
        return date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise reviews.ReviewRefused("Pick a period.") from exc


class ReviewsView(AccessPageView):
    template_name = "access/reviews.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from .models import AccessReview

        context = super().get_context_data(**kwargs)
        from . import cadence

        quarters = reviews.recent_quarters()
        state = cadence.status()
        context.update(
            {
                "crumbs": [("Reviews", "")],
                "cadence": state,
                "attesters": cadence.attesters(),
                "reminder_days": cadence.reminder_days(),
                "due_days": cadence.due_days(),
                "open_reviews": list(AccessReview.objects.filter(status=AccessReview.Status.OPEN)),
                "signed_reviews": list(AccessReview.objects.filter(status=AccessReview.Status.SIGNED)[:50]),
                # Each tile: the quarter, its signed review, and an open one for the same period.
                "quarters": [
                    (
                        q,
                        reviews.covered(q),
                        next(
                            (
                                r
                                for r in AccessReview.objects.filter(status=AccessReview.Status.OPEN)
                                if (r.period_start, r.period_end) == (q.start, q.end)
                            ),
                            None,
                        ),
                    )
                    for q in quarters
                ],
                # ?period=<key> (a tile's "Open review") pre-selects the form's period.
                "preselect": self.request.GET.get("period", ""),
                "scopes": AccessReview.Scope.choices,
                "can_open": not reviews.open_refusal(self.request.user),
                "open_refusal": reviews.open_refusal(self.request.user),
                "unresolved": reviews.unresolved_items(),
            }
        )
        return context


@require_POST
@staff_required
def review_open(request: HttpRequest) -> HttpResponse:
    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    try:
        start, end = _parse_period(request)
        review = reviews.open_review(
            period_start=start,
            period_end=end,
            scope=request.POST.get("scope", "privileged"),
            actor=request.user,
            note=request.POST.get("note", "").strip()[:2000],
            request_id=getattr(request, "id", "") or "",  # RequestIDMiddleware sets request.id (T3-4)
        )
    except reviews.ReviewRefused as exc:
        messages.error(request, str(exc))
        return redirect("access:reviews")
    messages.success(request, f"Review opened with {review.items.count()} account(s). Decide every row, then sign.")
    return redirect("access:review_detail", pk=review.pk)


class ReviewDetailView(AccessPageView):
    template_name = "access/review_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from .models import AccessReviewItem

        context = super().get_context_data(**kwargs)
        review = _review_or_404(self.kwargs["pk"])
        items = list(review.items.select_related("user", "decided_by"))
        d = reviews.delta(review)
        new = set(d["new"])
        me = self.request.user.pk
        rows = [
            {
                "item": item,
                "is_new": item.user_label in new,
                "is_me": item.user_id == me,
                "facts": item.facts or {},
                "approval": _approval_for(item),
            }
            for item in items
        ]
        # New accounts first, then pending, then the rest: what needs eyes is at the top.
        rows.sort(key=lambda r: (not r["is_new"], r["item"].is_decided, r["item"].user_label.lower()))
        attester_refusal = reviews.attester_refusal(self.request.user)
        counts = reviews.live_counts(review) if not review.is_signed else dict(review.summary)
        context.update(
            {
                "crumbs": [("Reviews", reverse("access:reviews")), (f"#{review.pk}", "")],
                "review": review,
                "rows": rows,
                "counts": counts,
                "delta": d,
                "can_decide": not review.is_signed and not attester_refusal,
                "attester_refusal": attester_refusal,
                "pending": sum(1 for r in rows if not r["item"].is_decided),
                "decisions": [
                    (AccessReviewItem.Decision.CONFIRMED, "Confirm"),
                    (AccessReviewItem.Decision.REMOVE, "Remove"),
                    (AccessReviewItem.Decision.FLAGGED, "Flag"),
                ],
            }
        )
        return context


def _approval_for(item: Any) -> Any:
    if not item.follow_up.startswith("approval:") or not item.follow_up[9:].isdigit():
        return None
    from apps.approvals.models import ApprovalRequest

    return ApprovalRequest.objects.filter(pk=int(item.follow_up[9:])).first()


@require_POST
@staff_required
def review_decide(request: HttpRequest, pk: int) -> HttpResponse:
    """One row's decision, or *confirm all pending* (``action=confirm_all``)."""
    from .models import AccessReviewItem

    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    review = _review_or_404(pk)
    source = f"web:{redact_path(request.path)}"
    try:
        if request.POST.get("action") == "confirm_all":
            done = reviews.confirm_all(review, actor=request.user)
            text = f"{done['confirmed']} account(s) confirmed."
            if done["skipped"]:
                text += " Your own row was skipped; another attester decides it, or flag it."
            messages.success(request, text)
        else:
            item = get_object_or_404(AccessReviewItem, pk=_posted_pk(request, "item"), review=review)
            reviews.decide(
                item,
                request.POST.get("decision", ""),
                actor=request.user,
                note=request.POST.get("note", "").strip()[:2000],
                source=source,
            )
            messages.success(request, f"{item.user_label}: {item.get_decision_display().lower()}.")
    except reviews.ReviewRefused as exc:
        messages.error(request, str(exc))
    return redirect("access:review_detail", pk=pk)


@require_POST
@staff_required
def review_sign(request: HttpRequest, pk: int) -> HttpResponse:
    from apps.smallstack.client_ip import get_client_ip

    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    review = _review_or_404(pk)
    try:
        reviews.sign(
            review,
            actor=request.user,
            typed_name=request.POST.get("signed_name", ""),
            note=request.POST.get("note", "").strip()[:2000],
            request_id=getattr(request, "id", "") or "",  # RequestIDMiddleware sets request.id (T3-4)
            signed_from=get_client_ip(request) or "",
        )
    except reviews.ReviewRefused as exc:
        messages.error(request, str(exc))
        return redirect("access:review_detail", pk=pk)
    messages.success(request, f"Review #{review.pk} signed. It is now read-only evidence.")
    return redirect("access:review_detail", pk=pk)


@access_reader_required
def review_csv(request: HttpRequest, pk: int) -> HttpResponseBase:
    review = _review_or_404(pk)
    return _csv_response(
        f"access-review-{review.pk}-{review.period_start:%Y%m%d}-{review.period_end:%Y%m%d}.csv",
        list(reviews.REVIEW_CSV_COLUMNS),
        reviews.review_csv_rows(review),
    )


@access_reader_required
def review_json(request: HttpRequest, pk: int) -> HttpResponse:
    review = _review_or_404(pk)
    response = JsonResponse(reviews.review_payload(review), json_dumps_params={"indent": 2})
    response["Content-Disposition"] = f'attachment; filename="access-review-{review.pk}.json"'
    return response


class ReviewPrintView(AccessPageView):
    """The signed review as one printable page: the auditor's PDF."""

    template_name = "access/review_print.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        review = _review_or_404(self.kwargs["pk"])
        context.update(
            {
                "review": review,
                "items": list(review.items.select_related("user")),
                "counts": dict(review.summary) if review.is_signed else reviews.live_counts(review),
                "brand": getattr(settings, "BRAND_NAME", "SmallStack"),
                "generated_at": timezone.now(),
            }
        )
        return context


# --- Evidence (the one-touch audit pack) ---------------------------------------------
# Read-only: every sheet is built by apps/access/evidence.py from what the app
# records; the page previews one sheet at a time and the exports use the same
# build, so what's downloaded is what was previewed.


class EvidenceArgsError(ValueError):
    """The request named a period or scope the pack can't be built for."""


def _evidence_args(request: HttpRequest) -> tuple[Any, Any, str]:
    """``?period=<start>_<end>`` (a quarter key) or ``?from=&to=``, and
    ``?scope=``. Nothing given → the last complete quarter, privileged.
    Something given that can't be used (a bad date, a period that ends
    before it starts, an unknown scope) raises :class:`EvidenceArgsError`
    with the reason, as the CLI refuses, rather than quietly building a
    different pack (T4-1)."""
    from datetime import date

    from .models import AccessReview

    scope = request.GET.get("scope", "") or AccessReview.Scope.PRIVILEGED
    if scope not in AccessReview.Scope.values:
        raise EvidenceArgsError(f"scope must be one of {', '.join(AccessReview.Scope.values)}.")
    key = request.GET.get("period", "")
    start_text, end_text = request.GET.get("from", ""), request.GET.get("to", "")
    if key and key != "custom":
        if "_" not in key:
            raise EvidenceArgsError("period must be a quarter key (YYYY-MM-DD_YYYY-MM-DD).")
        start_text, _, end_text = key.partition("_")
    if not start_text and not end_text:
        q = reviews.recent_quarters(1)[0]
        return q.start, q.end, scope
    try:
        start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
    except ValueError as exc:
        raise EvidenceArgsError("from and to must be dates (YYYY-MM-DD).") from exc
    if end < start:
        raise EvidenceArgsError("The period ends before it starts.")
    return start, end, scope


def _evidence_args_or_default(request: HttpRequest) -> tuple[Any, Any, str]:
    """For the HTML pages: the asked-for period, or the default with the
    reason shown as a message, so the page never silently shows another
    period than the one asked for."""
    try:
        return _evidence_args(request)
    except EvidenceArgsError as exc:
        q = reviews.recent_quarters(1)[0]
        messages.error(request, f"{exc} Showing {q.label} instead.")
        return q.start, q.end, "privileged"


def _evidence_querystring(start: Any, end: Any, scope: str) -> str:
    return f"from={start.isoformat()}&to={end.isoformat()}&scope={scope}"


class EvidenceView(AccessPageView):
    template_name = "access/evidence.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from . import evidence
        from .models import AccessReview

        context = super().get_context_data(**kwargs)
        start, end, scope = _evidence_args_or_default(self.request)
        tab = self.request.GET.get("tab", "cover")
        if tab not in ("cover", "packs") and tab not in evidence.sheet_keys():
            raise Http404("No such sheet.")
        # The counts for every tab are cheap enough to build once; the rows
        # of the selected sheet are what the table shows.
        pack = evidence.build(start, end, scope=scope, generated_by=self.request.user)
        sheet = pack.sheet(tab) if tab not in ("cover", "packs") else None
        from apps.smallstack.pagination import PAGE_SIZE_CHOICES, page_size_from

        rows = list(sheet.rows) if sheet else []
        per_page = page_size_from(self.request, PAGE_SIZE_CHOICES)
        page = paginate_queryset(rows, self.request, page_size=per_page)
        quarters = reviews.recent_quarters(6)
        selected_quarter = next((q.key for q in quarters if (q.start, q.end) == (start, end)), "custom")
        context.update(
            {
                "crumbs": [("Evidence", "")],
                "page_sizes": PAGE_SIZE_CHOICES,
                "per_page": per_page,
                # The date inputs show for a custom period, or when "Custom" was just picked.
                "custom": selected_quarter == "custom" or self.request.GET.get("period") == "custom",
                "bundles": list(EvidenceBundle.objects.select_related("review")[:24]),
                "can_store": not reviews.open_refusal(self.request.user),
                "keep": getattr(settings, "SMALLSTACK_ACCESS_EVIDENCE_KEEP", 24),
                "pack": pack,
                "sheet": sheet,
                "tab": tab,
                "page_obj": page,
                "rows": page.object_list,
                "start": start,
                "end": end,
                "scope": scope,
                "scopes": AccessReview.Scope.choices,
                "quarters": quarters,
                "selected_quarter": selected_quarter,
                "qs": _evidence_querystring(start, end, scope),
                "summary_items": [
                    (k, v) for k, v in (sheet.summary.items() if sheet else []) if not isinstance(v, dict)
                ],
                "cover_markdown": evidence.cover_markdown(pack) if tab == "cover" else "",
            }
        )
        return context


@access_reader_required
def evidence_sheet_csv(request: HttpRequest, key: str) -> HttpResponseBase:
    from . import evidence

    if key not in evidence.sheet_keys():
        raise Http404("No such sheet.")
    try:
        start, end, scope = _evidence_args(request)
    except EvidenceArgsError as exc:
        return HttpResponseBadRequest(str(exc), content_type="text/plain")
    pack = evidence.build(start, end, scope=scope, generated_by=request.user, only=[key])
    sheet = pack.sheet(key)
    return _csv_response(f"{evidence.bundle_name(pack)}-{key}.csv", list(sheet.columns), sheet.rows)


@access_reader_required
def evidence_json(request: HttpRequest) -> HttpResponse:
    from . import evidence

    try:
        start, end, scope = _evidence_args(request)
    except EvidenceArgsError as exc:
        return HttpResponseBadRequest(str(exc), content_type="text/plain")
    pack = evidence.build(start, end, scope=scope, generated_by=request.user)
    response = JsonResponse(pack.as_dict(), json_dumps_params={"indent": 2, "default": str})
    response["Content-Disposition"] = f'attachment; filename="{evidence.bundle_name(pack)}.json"'
    return response


@access_reader_required
def evidence_zip(request: HttpRequest) -> HttpResponse:
    from . import evidence

    try:
        start, end, scope = _evidence_args(request)
    except EvidenceArgsError as exc:
        return HttpResponseBadRequest(str(exc), content_type="text/plain")
    pack = evidence.build(start, end, scope=scope, generated_by=request.user)
    data = evidence.bundle_zip(pack)
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{evidence.bundle_name(pack)}.zip"'
    response["X-Content-SHA256"] = hashlib.sha256(data).hexdigest()  # as a stored pack's (G-1)
    return response


@require_POST
@staff_required
def evidence_store(request: HttpRequest) -> HttpResponse:
    """Store the previewed pack as a dated bundle with its SHA-256. Who may
    open a review may store a pack (an attester or a superuser)."""
    from . import cadence
    from .models import EvidenceBundle

    if not can_read_access(request.user):
        raise PermissionDenied(READ_ACCESS_REFUSAL)
    if reviews.open_refusal(request.user):
        messages.error(
            request,
            "Storing a pack needs an Access attester (access.sign_accessreview) or a superuser. "
            "You can still download it.",
        )
        from urllib.parse import urlencode

        # Only the period fields: never echo csrfmiddlewaretoken into a URL (G4-9).
        keep = urlencode({k: request.POST[k] for k in ("period", "from", "to", "scope") if request.POST.get(k)})
        return redirect(f"{reverse('access:evidence')}?{keep}" if keep else reverse("access:evidence"))
    # The POST carries the GET form's fields; read them as the GET views do.
    request.GET = request.POST  # type: ignore[assignment]
    try:
        start, end, scope = _evidence_args(request)
    except EvidenceArgsError as exc:
        messages.error(request, f"Nothing stored: {exc}")
        return redirect("access:evidence")
    bundle = cadence.store_bundle(start, end, scope, reason=EvidenceBundle.Reason.MANUAL, actor=request.user)
    messages.success(
        request,
        f"Stored evidence pack #{bundle.pk} for {bundle.period_label} "
        f"({bundle.size:,} bytes, SHA-256 {bundle.sha256[:12]}…).",
    )
    return redirect(f"{reverse('access:evidence')}?{_evidence_querystring(start, end, scope)}&tab=packs")


def bundle_response(bundle: Any) -> HttpResponse:
    """The stored file as stored, with its digest in ``X-Content-SHA256``."""
    import os

    with bundle.file.open("rb") as fh:
        data = fh.read()
    response = HttpResponse(data, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{os.path.basename(bundle.file.name)}"'
    response["X-Content-SHA256"] = bundle.sha256
    return response


@access_reader_required
def evidence_pack(request: HttpRequest, pk: int) -> HttpResponse:
    from .models import EvidenceBundle

    return bundle_response(get_object_or_404(EvidenceBundle, pk=pk))


class EvidencePrintView(AccessPageView):
    """The cover, the roster, the leavers and the attestations on one
    printable page: the auditor's PDF."""

    template_name = "access/evidence_print.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from . import evidence

        context = super().get_context_data(**kwargs)
        start, end, scope = _evidence_args_or_default(self.request)
        pack = evidence.build(
            start, end, scope=scope, generated_by=self.request.user, only=["roster", "leavers", "findings", "reviews"]
        )
        context.update({"pack": pack, "sheets": pack.sheets, "qs": _evidence_querystring(start, end, scope)})
        return context
