"""User Manager views — CRUDView config + bespoke overrides."""

from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Max
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from apps.activity.models import RequestLog
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

from .forms import UserAccountForm, UserProfileForm

User = get_user_model()


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
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]

    # List rendering — TableDisplay + per-row action filter (was UserTable
    # + UserActionsColumn pre-v0.12, when django-tables2 was still around).
    list_fields = ["username", "email", "name", "timezone", "is_staff", "is_active"]
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
        if suffix == "form":
            return ["accounts/user_form.html"]
        if suffix == "list":
            return ["usermanager/user_list.html"]
        return super()._get_template_names(suffix)

    @classmethod
    def _make_view(cls, base_class):
        """Override to inject custom logic into update and detail views."""
        from apps.smallstack.crud import _CRUDDeleteBase, _CRUDListBase, _CRUDUpdateBase

        view_class = super()._make_view(base_class)

        if base_class is _CRUDListBase:
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
            # Add profile form + activity stats to edit view

            def get_context_data(self, **kwargs):
                context = super(view_class, self).get_context_data(**kwargs)
                user_obj = self.object
                profile = getattr(user_obj, "profile", None)

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

                return context

            def post(self, request, *args, **kwargs):
                self.object = self.get_object()
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
            # Prevent users from deleting themselves
            def delete(self, request, *args, **kwargs):
                self.object = self.get_object()
                if self.object.pk == request.user.pk:
                    from django.http import HttpResponseForbidden

                    return HttpResponseForbidden("You cannot delete your own account.")
                return super(view_class, self).delete(request, *args, **kwargs)

            view_class.delete = delete

        return view_class


def _get_dashboard_stats() -> dict[str, int]:
    """Build dashboard stats for the user manager list page."""
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)
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
    thirty_days_ago = now - timezone.timedelta(days=30)
    seven_days_ago = now - timezone.timedelta(days=7)

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


def _user_list_row(u) -> str:
    """A clickable user row for the stat modal: avatar · name · meta · chevron."""
    return format_html(
        '<a class="stat-list-row" href="{}">'
        '<span class="stat-list-avatar" aria-hidden="true">{}</span>'
        '<span class="stat-list-name">{}</span>'
        '<span class="stat-list-meta">{}</span>'
        '<span class="stat-list-chevron" aria-hidden="true">→</span>'
        "</a>",
        reverse("manage/users-update", args=[u.pk]),
        (u.username[:2] or "?").upper(),
        u.username,
        u.email or "No email on file",
    )


@staff_member_required
def user_stat_detail(request, stat_type: str) -> HttpResponse:
    """HTMX endpoint returning HTML for stat card drill-down modals."""
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)
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
            format_html(
                # Links into the Timezones dashboard filtered to this zone
                # (its search matches the raw IANA name, e.g. America/New_York).
                '<a class="stat-list-row" href="{}?{}">'
                '<span class="stat-list-name">{}</span>'
                '<span class="stat-list-count">{}</span>'
                '<span class="stat-list-chevron" aria-hidden="true">→</span>'
                "</a>",
                tz_dashboard,
                urlencode({"q": t["timezone"]}),
                t["timezone"].split("/")[-1].replace("_", " "),
                t["count"],
            )
            for t in tz_counts
        ]
        empty_msg = "No timezones configured."

    if rows:
        body = format_html('<div class="stat-list">{}</div>', format_html_join("", "{}", ((r,) for r in rows)))
    else:
        body = format_html('<p class="stat-list-empty">{}</p>', empty_msg)
    return HttpResponse(body)
