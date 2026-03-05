"""Views for the activity dashboard."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, Max, Q
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.profile.models import UserProfile

from .models import RequestLog

User = get_user_model()


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that restricts access to staff users."""

    def test_func(self):
        return self.request.user.is_staff


class ActivityDashboardView(StaffRequiredMixin, TemplateView):
    """Staff-only overview dashboard — high-level stats only."""

    template_name = "activity/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = RequestLog.objects.all()
        max_rows = getattr(settings, "ACTIVITY_MAX_ROWS", 10000)

        total = qs.count()
        stats = qs.aggregate(
            avg_response_time=Avg("response_time_ms"),
            count_4xx=Count("pk", filter=Q(status_code__gte=400, status_code__lt=500)),
            count_5xx=Count("pk", filter=Q(status_code__gte=500)),
        )

        status_groups = []
        if total > 0:
            for label, low, high in [("2xx", 200, 300), ("3xx", 300, 400), ("4xx", 400, 500), ("5xx", 500, 600)]:
                count = qs.filter(status_code__gte=low, status_code__lt=high).count()
                if count:
                    status_groups.append({"label": label, "count": count})

        top_paths = (
            qs.values("path")
            .annotate(hits=Count("pk"))
            .order_by("-hits")[:5]
        )

        recent = qs.select_related("user")[:5]

        # User stats
        user_count = User.objects.count()
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_signup_count = User.objects.filter(date_joined__gte=thirty_days_ago).count()

        top_themes = (
            UserProfile.objects.values("theme_preference")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )
        top_palettes = (
            UserProfile.objects.exclude(color_palette="")
            .values("color_palette")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )

        top_users = (
            RequestLog.objects.filter(user__isnull=False)
            .values("user__username")
            .annotate(hits=Count("pk"))
            .order_by("-hits")[:5]
        )

        context.update({
            "total_requests": total,
            "max_rows": max_rows,
            "avg_response_time": round(stats["avg_response_time"] or 0),
            "count_4xx": stats["count_4xx"],
            "count_5xx": stats["count_5xx"],
            "status_groups": status_groups,
            "top_paths": top_paths,
            "recent_requests": recent,
            "user_count": user_count,
            "recent_signup_count": recent_signup_count,
            "top_themes": top_themes,
            "top_palettes": top_palettes,
            "top_users": top_users,
        })
        return context


class RequestListView(StaffRequiredMixin, TemplateView):
    """Staff-only detail view for request logs.

    Returns partial HTML when called via htmx (for polling/refresh),
    or the full page for normal navigation.
    """

    template_name = "activity/requests.html"
    partial_template_name = "activity/partials/recent_requests.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = RequestLog.objects.all()

        top_paths = (
            qs.values("path")
            .annotate(hits=Count("pk"), avg_time=Avg("response_time_ms"))
            .order_by("-hits")[:25]
        )

        recent = qs.select_related("user")[:50]

        status_groups = []
        total = qs.count()
        if total > 0:
            for label, low, high in [("2xx", 200, 300), ("3xx", 300, 400), ("4xx", 400, 500), ("5xx", 500, 600)]:
                count = qs.filter(status_code__gte=low, status_code__lt=high).count()
                if count:
                    status_groups.append({"label": label, "count": count})

        context.update({
            "top_paths": top_paths,
            "recent_requests": recent,
            "status_groups": status_groups,
            "total_requests": total,
        })
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if request.htmx:
            return TemplateResponse(request, self.partial_template_name, context)
        return TemplateResponse(request, self.template_name, context)


class UserActivityView(StaffRequiredMixin, TemplateView):
    """Staff-only detail view for per-user activity.

    Returns partial HTML when called via htmx,
    or the full page for normal navigation.
    """

    template_name = "activity/users.html"
    partial_template_name = "activity/partials/recent_user_activity.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        top_users = (
            RequestLog.objects.filter(user__isnull=False)
            .values("user__username", "user__pk")
            .annotate(
                hits=Count("pk"),
                avg_time=Avg("response_time_ms"),
                last_seen=Max("timestamp"),
            )
            .order_by("-hits")[:25]
        )

        recent_user_activity = (
            RequestLog.objects.filter(user__isnull=False)
            .select_related("user")
            .order_by("-timestamp")[:50]
        )

        active_user_pks = (
            RequestLog.objects.filter(user__isnull=False)
            .values_list("user__pk", flat=True)
            .distinct()
        )
        inactive_users = User.objects.exclude(pk__in=active_user_pks).order_by("-date_joined")[:25]

        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_signups = User.objects.filter(date_joined__gte=thirty_days_ago).order_by("-date_joined")[:25]

        top_themes = (
            UserProfile.objects.values("theme_preference")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )
        top_palettes = (
            UserProfile.objects.exclude(color_palette="")
            .values("color_palette")
            .annotate(count=Count("pk"))
            .order_by("-count")
        )

        context.update({
            "top_users": top_users,
            "recent_user_activity": recent_user_activity,
            "inactive_users": inactive_users,
            "recent_signups": recent_signups,
            "user_count": User.objects.count(),
            "top_themes": top_themes,
            "top_palettes": top_palettes,
        })
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if request.htmx:
            return TemplateResponse(request, self.partial_template_name, context)
        return TemplateResponse(request, self.template_name, context)
