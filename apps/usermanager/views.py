"""User Manager views — CRUDView config + bespoke overrides."""

import logging
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from apps.activity.models import RequestLog
from apps.smallstack.audit import CHANGE, log_action
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from .forms import UserAccountForm, UserCreateForm, UserProfileForm

User = get_user_model()
logger = logging.getLogger(__name__)


def _record_account_action(request, target, message: str) -> None:
    """Audit and log a staff action on someone's account (a reset link, an
    unlock): who did it, to whom, and what happened. Never raises, so the
    record can't break the action it describes."""
    logger.info("usermanager: %s by %s for %s (pk=%s)", message, request.user, target.get_username(), target.pk)
    try:
        log_action(request.user, target, CHANGE, message)
    except Exception:  # noqa: BLE001 — the action already happened; say the audit row didn't
        logger.exception("usermanager: couldn't write the audit entry for %r on user pk=%s", message, target.pk)


CHANGE_USER = "accounts.change_user"
VIEW_USER = "accounts.view_user"


def can_edit_account(actor: Any, target: Any) -> bool:
    """Whether ``actor`` may change ``target``'s account here (fields, the
    staff and active flags, a reset link, an unlock): ``accounts.change_user``,
    the permission the shipped *User manager* group grants, and only a
    superuser may change a superuser's account. Superusers hold every perm."""
    if not actor.has_perm(CHANGE_USER):
        return False
    return not target.is_superuser or actor.is_superuser


def sign_in_refusal(actor: Any, target: Any) -> str:
    """Why ``actor`` may not change ``target``'s password, email or username
    or send it a link, beyond :func:`can_edit_account` ("" when they may):
    the subset rule in :func:`apps.access.services.sign_in_refusal`."""
    from apps.access.services import sign_in_refusal as rule

    return rule(actor, target)


def _active_superuser_count(exclude_pk=None) -> int:
    qs = User.objects.filter(is_superuser=True, is_active=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def _render_name(value, obj):
    """Show the user's full name when set, else the username."""
    return obj.get_full_name() or obj.username


def _render_timezone(value, obj):
    """Show the city part of the user's profile timezone (e.g. "New York" for
    ``America/New_York``) with the full tz name as a tooltip; em-dash when
    no timezone is set."""
    profile = getattr(obj, "profile", None)
    tz = profile.timezone if profile and profile.timezone else ""
    if not tz:
        return mark_safe('<span style="color: var(--body-quiet-color);">—</span>')
    city = tz.split("/")[-1].replace("_", " ")
    return format_html('<span title="{}">{}</span>', tz, city)


class UserCRUDView(CRUDView):
    model = User
    fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]
    url_base = "manage/users"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    # Every page asks for Django's model permissions (view_user to read,
    # add_user / change_user / delete_user to write; superusers hold all
    # four), as Django admin and Explorer do. Search follows the same check.
    model_permissions = True
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]

    # List rendering — TableDisplay + per-row action filter (was UserTable
    # + UserActionsColumn pre-v0.12, when django-tables2 was still around).
    list_fields = ["username", "email", "name", "timezone", "is_staff", "is_active"]
    # An address is the longest thing on a row; the username (the link) needs less.
    column_widths = {"username": "180px", "email": "280px", "timezone": "170px"}
    link_field = "username"   # clickable username → goes to update view
    field_transforms = {
        "first_name": "preview",
        "name": _render_name,
        "timezone": _render_timezone,
    }

    # Opted into the unified search index by default. Lights up an MCP
    # `search_users` tool so Claude Desktop can answer "find the user
    # named X" out of the box, plus surfaces users in the global
    # /smallstack/search/ page and topbar omnibar.
    enable_search = True
    search_fields = ["username", "email", "first_name", "last_name"]
    search_display = "username"
    search_subtitle = "email"

    @classmethod
    def row_actions(cls, obj, request, default_actions):
        """Don't render the Delete button on the current user's own row —
        admins shouldn't be able to delete themselves out of the system.
        The corresponding write gate is in the ``_CRUDDeleteBase.delete``
        override below (renders + view both deny; defense in depth)."""
        if request and getattr(request.user, "pk", None) == obj.pk:
            return [a for a in default_actions if not a.get("is_delete")]
        return default_actions

    @classmethod
    def get_list_queryset(cls, qs, request):
        """Prefetch the profile for the timezone column. Free-text ``?q=``
        search (over ``search_fields``), filtering, sort, and pagination are
        all handled by the framework's list view — no custom queryset needed."""
        return qs.select_related("profile")

    @classmethod
    def _get_template_names(cls, suffix):
        # The CRUD engine asks for suffix "create"/"edit" (plus the legacy
        # "form"); match all three so the custom tabbed user form keeps being
        # used. v0.11.19 renamed the suffix, so this override stopped matching
        # and the create/edit pages silently fell back to the generic CRUD
        # form — losing the Profile + Activity tabs.
        if suffix in ("form", "create", "edit"):
            return ["accounts/user_form.html"]
        if suffix == "list":
            return ["usermanager/user_list.html"]
        return super()._get_template_names(suffix)

    @classmethod
    def _make_view(cls, base_class):
        """Override to inject custom logic into update and detail views."""
        from apps.smallstack.crud import (
            _CRUDCreateBase,
            _CRUDDeleteBase,
            _CRUDListBase,
            _CRUDUpdateBase,
        )

        view_class = super()._make_view(base_class)

        if base_class is _CRUDCreateBase:
            # Create with a password set up front, so the new account is
            # immediately usable (never passwordless). The Invite action is
            # the email-based alternative.
            def get_form_class(self):
                return UserCreateForm

            view_class.get_form_class = get_form_class

        elif base_class is _CRUDListBase:
            # Add the dashboard stat cards to the list page. Search / filter /
            # sort / pagination are all handled by the base list view (the
            # toolbar's ?q= search reuses search_fields), so no get_queryset or
            # get_template_names override is needed here anymore.
            def get_context_data(self, **kwargs):
                context = super(view_class, self).get_context_data(**kwargs)
                context["dashboard_stats"] = _get_dashboard_stats()
                return context

            view_class.get_context_data = get_context_data

        elif base_class is _CRUDUpdateBase:
            # Add profile form + activity stats to edit view. The page opens
            # with view_user (read-only without change_user); post() below
            # refuses the write.
            view_class._model_permission = "view"

            def get_context_data(self, **kwargs):
                context = super(view_class, self).get_context_data(**kwargs)
                user_obj = self.object
                profile = getattr(user_obj, "profile", None)
                context["can_edit_account"] = can_edit_account(self.request.user, user_obj)

                # Profile form
                if "profile_form" not in context:
                    if self.request.method == "POST":
                        context["profile_form"] = UserProfileForm(
                            self.request.POST,
                            self.request.FILES,
                            instance=profile,
                            prefix="profile",
                        )
                    else:
                        context["profile_form"] = UserProfileForm(
                            instance=profile,
                            prefix="profile",
                        )

                # Activity stats
                context["activity_stats"] = _get_user_activity_stats(user_obj)

                # The Access tab: groups, counts, recent changes; the full
                # explanation lives at /smallstack/access/users/<pk>/.
                from apps.access.services import user_access_summary

                context["access_summary"] = user_access_summary(user_obj)
                context["sign_in_refusal"] = sign_in_refusal(self.request.user, user_obj)

                if not context["can_edit_account"]:
                    for each in (context.get("form"), context.get("profile_form")):
                        for field in getattr(each, "fields", {}).values():
                            field.disabled = True

                return context

            def post(self, request, *args, **kwargs):
                from django.http import HttpResponseForbidden

                self.object = self.get_object()
                if not can_edit_account(request.user, self.object):
                    if self.object.is_superuser and request.user.has_perm(CHANGE_USER):
                        return HttpResponseForbidden("Only a superuser can change a superuser account.")
                    return HttpResponseForbidden(f"Changing an account needs the {CHANGE_USER} permission.")
                refusal = sign_in_refusal(request.user, self.object)
                if refusal:
                    from apps.access.services import SIGN_IN_FIELDS

                    for name in SIGN_IN_FIELDS:
                        posted = request.POST.get(name)
                        if posted is not None and posted.strip() != (getattr(self.object, name) or ""):
                            return HttpResponseForbidden(refusal)
                # Capture the ORIGINAL flag values before form validation —
                # form.is_valid() runs construct_instance(), which mutates
                # self.object to the submitted values, so reading them after
                # would compare new-vs-new and defeat the guardrails.
                was_staff = self.object.is_staff
                was_active = self.object.is_active
                is_superuser = self.object.is_superuser
                form = self.get_form()
                profile = getattr(self.object, "profile", None)
                profile_form = UserProfileForm(
                    request.POST,
                    request.FILES,
                    instance=profile,
                    prefix="profile",
                )
                if form.is_valid() and profile_form.is_valid():
                    from django.contrib import messages
                    from django.db import transaction
                    from django.http import HttpResponseRedirect
                    from django.urls import reverse

                    # ── Guardrails (compare ORIGINAL vs submitted) ──────
                    new_is_staff = form.cleaned_data.get("is_staff", False)
                    new_is_active = form.cleaned_data.get("is_active", False)
                    editing_self = self.object.pk == request.user.pk
                    guard_error = None
                    if editing_self and was_staff and not new_is_staff:
                        guard_error = "You can't remove your own staff access."
                    elif editing_self and was_active and not new_is_active:
                        guard_error = "You can't deactivate your own account."
                    elif (
                        is_superuser
                        and not request.user.is_superuser
                        and (not new_is_active or not new_is_staff)
                    ):
                        guard_error = (
                            "Only a superuser can deactivate or remove staff from a superuser account."
                        )
                    elif (
                        is_superuser
                        and was_active
                        and not new_is_active
                        and _active_superuser_count(exclude_pk=self.object.pk) == 0
                    ):
                        guard_error = "You can't deactivate the last active superuser."
                    if guard_error:
                        messages.error(request, guard_error)
                        context = self.get_context_data(form=form)
                        context["profile_form"] = profile_form
                        return self.render_to_response(context)

                    with transaction.atomic():
                        # Save profile fields directly to avoid the
                        # User post_save signal overwriting our changes.
                        # (signals.save_user_profile calls profile.save()
                        # with stale in-memory data on every User save.)
                        profile_obj = profile_form.save(commit=False)
                        form.save()
                        # After User save + signal, force-write profile
                        # fields from the form's cleaned data.
                        profile_obj.save(
                            update_fields=[
                                f.name for f in profile_obj._meta.fields if f.name in profile_form.cleaned_data
                            ]
                        )
                    messages.success(request, "User updated successfully.")
                    url_base = self.crud_config._get_url_base()
                    return HttpResponseRedirect(reverse(f"{url_base}-update", kwargs={"pk": self.object.pk}))
                # Re-render with errors
                context = self.get_context_data(form=form)
                context["profile_form"] = profile_form
                return self.render_to_response(context)

            view_class.get_context_data = get_context_data
            view_class.post = post

        elif base_class is _CRUDDeleteBase:
            # Guard self-delete and superuser/last-superuser deletion. NOTE:
            # Django 5+/6 DeleteView routes POST through post()/form_valid(),
            # NOT delete() — guarding delete() alone is a no-op (the reason the
            # old self-delete guard silently stopped working). Guard in post().
            def post(self, request, *args, **kwargs):
                from django.http import HttpResponseForbidden

                self.object = self.get_object()
                target = self.object
                if target.pk == request.user.pk:
                    return HttpResponseForbidden("You cannot delete your own account.")
                if target.is_superuser and not request.user.is_superuser:
                    return HttpResponseForbidden("Only a superuser can delete a superuser account.")
                if (
                    target.is_superuser
                    and target.is_active
                    and _active_superuser_count(exclude_pk=target.pk) == 0
                ):
                    return HttpResponseForbidden("You can't delete the last active superuser.")
                return super(view_class, self).post(request, *args, **kwargs)

            view_class.post = post

        return view_class


def _get_dashboard_stats() -> dict[str, int]:
    """Build dashboard stats for the user manager list page."""
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    all_users = User.objects.filter(is_active=True)
    total = all_users.count()
    recent = all_users.filter(date_joined__gte=thirty_days_ago).count()
    staff = all_users.filter(is_staff=True).count()
    unique_tz = (
        all_users.select_related("profile")
        .exclude(profile__timezone="")
        .exclude(profile__timezone__isnull=True)
        .values("profile__timezone")
        .distinct()
        .count()
    )
    return {
        "recent": recent,
        "total": total,
        "staff": staff,
        "unique_tz": unique_tz,
    }


def _get_user_activity_stats(user_obj) -> dict[str, Any]:
    """Build activity stats dict for a user."""
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    logs = RequestLog.objects.filter(user=user_obj)
    total = logs.count()
    last_30 = logs.filter(timestamp__gte=thirty_days_ago)
    last_7 = logs.filter(timestamp__gte=seven_days_ago)

    agg = last_30.aggregate(
        count=Count("id"),
        avg_response=Avg("response_time_ms"),
        last_seen=Max("timestamp"),
    )

    # Top paths (last 30 days)
    top_paths = last_30.values("path").annotate(hits=Count("id")).order_by("-hits")[:5]

    # Status code breakdown (last 30 days)
    status_breakdown = last_30.values("status_code").annotate(count=Count("id")).order_by("-count")[:5]

    # Daily request counts for last 7 days (for sparkline)
    from django.db.models.functions import TruncDate

    daily_counts = last_7.annotate(day=TruncDate("timestamp")).values("day").annotate(count=Count("id")).order_by("day")

    return {
        "total_requests": total,
        "last_30_count": agg["count"] or 0,
        "avg_response_ms": round(agg["avg_response"] or 0),
        "last_seen": agg["last_seen"],
        "top_paths": list(top_paths),
        "status_breakdown": list(status_breakdown),
        "daily_counts": list(daily_counts),
        "last_7_count": last_7.count(),
        "member_since": user_obj.date_joined,
    }


def _user_list_row(u):
    """A clickable user row for the stat modal: avatar · name · meta · chevron."""
    return stat_list_row(
        u.username,
        href=reverse("manage/users-update", args=[u.pk]),
        avatar=True,
        meta=u.email or "No email on file",
    )


@staff_member_required
def user_stat_detail(request, stat_type: str) -> HttpResponse:
    """HTMX endpoint returning HTML for stat card drill-down modals. Lists
    accounts, so it asks what the list page asks (``accounts.view_user``)."""
    if not request.user.has_perm(VIEW_USER):
        raise PermissionDenied(f"Listing accounts needs the {VIEW_USER} permission.")
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    users = User.objects.filter(is_active=True).order_by("username")

    rows: list = []
    empty_msg = "Nothing to show."

    if stat_type == "recent":
        rows = [_user_list_row(u) for u in users.filter(date_joined__gte=thirty_days_ago)]
        empty_msg = "No new users in the last 30 days."
    elif stat_type == "total":
        rows = [_user_list_row(u) for u in users]
        empty_msg = "No active users."
    elif stat_type == "staff":
        rows = [_user_list_row(u) for u in users.filter(is_staff=True)]
        empty_msg = "No staff users."
    elif stat_type == "timezones":
        from urllib.parse import urlencode

        from apps.profile.models import UserProfile

        tz_counts = (
            UserProfile.objects.exclude(timezone="")
            .exclude(timezone__isnull=True)
            .values("timezone")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        tz_dashboard = reverse("manage/users-timezones")
        rows = [
            # Links into the Timezones dashboard filtered to this zone
            # (its search matches the raw IANA name, e.g. America/New_York).
            stat_list_row(
                t["timezone"].split("/")[-1].replace("_", " "),
                href=f"{tz_dashboard}?{urlencode({'q': t['timezone']})}",
                count=t["count"],
            )
            for t in tz_counts
        ]
        empty_msg = "No timezones configured."

    return render_stat_list(rows, empty=empty_msg)


@require_POST
@staff_member_required
def send_user_link(request, pk: int) -> HttpResponse:
    """Email the user a set-password link (resend invite if they never set one,
    otherwise a standard branded password-reset link)."""
    from apps.accounts.views import send_setup_or_reset

    user = get_object_or_404(User, pk=pk)
    if not can_edit_account(request.user, user):
        raise PermissionDenied(f"Sending a link needs {CHANGE_USER} (and a superuser, for a superuser's account).")
    refusal = sign_in_refusal(request.user, user)
    if refusal:
        raise PermissionDenied(refusal)
    kind = send_setup_or_reset(request, user)
    if kind == "invite":
        messages.success(request, f"Invite link sent to {user.email}.")
        _record_account_action(request, user, "Sent an invite link")
    elif kind == "reset":
        messages.success(request, f"Password reset link sent to {user.email}.")
        _record_account_action(request, user, "Sent a password reset link")
    else:
        messages.error(request, "Couldn't send a link — this user has no email address on file.")
        logger.warning("usermanager: no link sent for user pk=%s (no email address) by %s", user.pk, request.user)
    return redirect("manage/users-update", pk=pk)


@require_POST
@staff_member_required
def unlock_user(request, pk: int) -> HttpResponse:
    """Clear django-axes failed-login lockouts for a user."""
    user = get_object_or_404(User, pk=pk)
    if not can_edit_account(request.user, user):
        raise PermissionDenied(f"Unlocking needs {CHANGE_USER} (and a superuser, for a superuser's account).")
    try:
        from axes.utils import reset

        reset(username=user.get_username())
    except Exception:
        logger.exception("usermanager: clearing login lockouts failed for user pk=%s by %s", user.pk, request.user)
        messages.error(request, "Couldn't clear lockouts for this account.")
    else:
        messages.success(request, f"Cleared login lockouts for {user.get_username()}.")
        _record_account_action(request, user, "Cleared login lockouts")
    return redirect("manage/users-update", pk=pk)
