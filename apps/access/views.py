"""The Access pages at /smallstack/access/: who may do what, why, and every change.

Reading needs a staff account holding ``accounts.view_user`` (what Django
admin and Explorer ask to list accounts; the *Access reviewer* and *User
manager* groups grant it). Changing a membership needs ``accounts.change_user``
(what Django admin asks for the same edit); revoking a token needs
``smallstack.change_apitoken``. Superusers hold all three.
"""

from __future__ import annotations

import csv
import json
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBase, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
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

from . import services
from .models import AccessEvent, ManagedGroup
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

    @staff_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        if not can_read_access(request.user):
            raise PermissionDenied(READ_ACCESS_REFUSAL)
        return view_func(request, *args, **kwargs)

    return _wrapped


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


class GroupDetailView(AccessPageView):
    template_name = "access/group_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        group = get_object_or_404(Group, pk=self.kwargs["pk"])
        managed = services.managed_for(group)
        declared = set(managed.declared_permissions or []) if managed else set()
        perms = group.permissions.select_related("content_type").order_by(
            "content_type__app_label", "content_type__model", "codename"
        )
        by_app: dict[str, list[dict[str, Any]]] = {}
        for perm in perms:
            name = services.perm_name(perm)
            by_app.setdefault(perm.content_type.app_label, []).append(
                {
                    "perm": name,
                    "label": perm.name,
                    "declared": name in declared,
                    "added": bool(managed) and name not in declared,
                }
            )
        members = list(group.user_set.order_by("username"))
        source_by_user = {}
        for event in AccessEvent.objects.filter(
            group=group, kind=AccessEvent.Kind.GROUP_ADDED, subject__in=members
        ).order_by("at"):
            source_by_user[event.subject_id] = event  # the latest wins
        context.update(
            {
                "crumbs": [("Groups", reverse("access:groups")), (group.name, "")],
                "group": group,
                "managed": managed,
                "declared_in_code": any(g.name == group.name for g in declared_groups()),
                "drift": managed.drift() if managed else None,
                "permissions_by_app": sorted(by_app.items()),
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


class UsersView(AccessPageView):
    template_name = "access/users.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        show = self.request.GET.get("show", "active")
        qs = services.users_with_access()
        if show == "active":
            qs = qs.filter(is_active=True)
        elif show == "staff":
            qs = qs.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
        elif show == "inactive":
            qs = qs.filter(is_active=False)
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(groups__name__icontains=q)
            ).distinct()
        page = paginate_queryset(qs, self.request, page_size=self.page_size)
        context.update({"crumbs": [("Users", "")], "page_obj": page, "users": page.object_list, "q": q, "show": show})
        return context


class UserDetailView(AccessPageView):
    template_name = "access/user_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        grants = services.effective_permissions(user)
        groups = list(user.groups.order_by("name"))
        perm = self.request.GET.get("perm", "").strip()
        context.update(
            {
                "crumbs": [("Users", reverse("access:users")), (user.get_username(), "")],
                "target": user,
                "groups": [{"group": g, "since": services.group_source_event(user, g)} for g in groups],
                "other_groups": Group.objects.exclude(pk__in=[g.pk for g in groups]).order_by("name"),
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
            }
        )
        return context


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
    if kind == "grants":
        qs = qs.filter(kind__in=AccessEvent.GRANTS)
    elif kind:
        qs = qs.filter(kind=kind)
    return qs


class EventsView(AccessPageView):
    template_name = "access/events.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        qs = _events_queryset(self.request)
        page = paginate_queryset(qs, self.request, page_size=self.page_size)
        context.update(
            {
                "crumbs": [("Changes", "")],
                "page_obj": page,
                "events": page.object_list,
                "who": self.request.GET.get("who", ""),
                "kind": self.request.GET.get("kind", ""),
                "kinds": AccessEvent.Kind.choices,
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
