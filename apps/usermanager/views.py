"""User Manager views — CRUDView config + bespoke overrides."""

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Max
from django.http import HttpResponse
from django.utils import timezone

from apps.activity.models import RequestLog
from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin

from .forms import UserAccountForm, UserProfileForm
from .tables import UserTable

User = get_user_model()


class UserCRUDView(CRUDView):
    model = User
    fields = ["username", "email", "first_name", "last_name", "is_staff", "is_active"]
    url_base = "manage/users"
    paginate_by = 10
    mixins = [StaffRequiredMixin]
    table_class = UserTable
    form_class = UserAccountForm
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]

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
            def get_queryset(self):
                qs = super(view_class, self).get_queryset().select_related("profile")
                q = self.request.GET.get("q", "").strip()
                if q:
                    from django.db.models import Q
                    qs = qs.filter(
                        Q(username__icontains=q)
                        | Q(email__icontains=q)
                        | Q(first_name__icontains=q)
                        | Q(last_name__icontains=q)
                    )
                return qs

            def get_context_data(self, **kwargs):
                context = super(view_class, self).get_context_data(**kwargs)
                # Stamp current_user_pk on the table so UserActionsColumn can
                # hide the delete button for the logged-in user's own row.
                table = context.get("table")
                if table is not None:
                    table.current_user_pk = self.request.user.pk
                # Dashboard stats
                context["dashboard_stats"] = _get_dashboard_stats()
                context["search_query"] = self.request.GET.get("q", "")
                return context

            def get_template_names(self):
                if self.request.headers.get("HX-Request"):
                    return ["usermanager/_user_table.html"]
                return super(view_class, self).get_template_names()

            view_class.get_queryset = get_queryset
            view_class.get_context_data = get_context_data
            view_class.get_template_names = get_template_names

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
                        profile_obj.save(update_fields=[
                            f.name for f in profile_obj._meta.fields
                            if f.name in profile_form.cleaned_data
                        ])
                    messages.success(request, "User updated successfully.")
                    url_base = self.crud_config._get_url_base()
                    return HttpResponseRedirect(
                        reverse(f"{url_base}-update", kwargs={"pk": self.object.pk})
                    )
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


def _get_dashboard_stats():
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


def _get_user_activity_stats(user_obj):
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
    top_paths = (
        last_30.values("path")
        .annotate(hits=Count("id"))
        .order_by("-hits")[:5]
    )

    # Status code breakdown (last 30 days)
    status_breakdown = (
        last_30.values("status_code")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )

    # Daily request counts for last 7 days (for sparkline)
    from django.db.models.functions import TruncDate
    daily_counts = (
        last_7.annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

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


@staff_member_required
def user_stat_detail(request, stat_type):
    """HTMX endpoint returning HTML for stat card drill-down modals."""
    now = timezone.now()
    thirty_days_ago = now - timezone.timedelta(days=30)
    users = User.objects.filter(is_active=True).order_by("username")

    if stat_type == "recent":
        items = users.filter(date_joined__gte=thirty_days_ago)
        rows = [{"label": u.username, "value": u.date_joined.strftime("%b %d, %Y")} for u in items]
        if not rows:
            rows = [{"label": "No new users in the last 30 days", "value": ""}]
    elif stat_type == "total":
        rows = [{"label": u.username, "value": u.email or "—"} for u in users]
    elif stat_type == "staff":
        items = users.filter(is_staff=True)
        rows = [{"label": u.username, "value": u.email or "—"} for u in items]
    elif stat_type == "timezones":
        from apps.profile.models import UserProfile
        tz_counts = (
            UserProfile.objects.exclude(timezone="")
            .exclude(timezone__isnull=True)
            .values("timezone")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        rows = [{"label": t["timezone"].split("/")[-1].replace("_", " "), "value": str(t["count"])} for t in tz_counts]
        if not rows:
            rows = [{"label": "No timezones configured", "value": ""}]
    else:
        rows = []

    html = '<table style="width:100%;"><thead><tr><th>Name</th><th>Detail</th></tr></thead><tbody>'
    for row in rows:
        html += (
            f'<tr>'
            f'<td style="font-size:0.85rem;">{row["label"]}</td>'
            f'<td style="font-size:0.85rem;text-align:right;">{row["value"]}</td>'
            f'</tr>'
        )
    html += '</tbody></table>'
    return HttpResponse(html)
