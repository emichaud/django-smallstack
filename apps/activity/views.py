"""Views for the activity dashboard."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Avg, Count, Max, Q
from django.http import Http404
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.profile.models import UserProfile
from apps.smallstack.pagination import paginate_queryset

from .models import RequestLog

User = get_user_model()


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that restricts access to staff users."""

    def test_func(self):
        return self.request.user.is_staff


class ActivityStatDetailView(StaffRequiredMixin, View):
    """Return a partial table for a dashboard stat card drill-down."""

    def get(self, request, stat):
        qs = RequestLog.objects.all()

        if stat == "requests":
            records = qs.select_related("user").order_by("-timestamp")[:100]
            return render(request, "activity/partials/activity_stat_detail.html", {"records": records})
        elif stat == "4xx":
            records = (
                qs.filter(status_code__gte=400, status_code__lt=500)
                .select_related("user").order_by("-timestamp")[:100]
            )
            return render(request, "activity/partials/activity_stat_detail.html", {"records": records})
        elif stat == "5xx":
            records = qs.filter(status_code__gte=500).select_related("user").order_by("-timestamp")[:100]
            return render(request, "activity/partials/activity_stat_detail.html", {"records": records})
        elif stat == "users":
            users = User.objects.order_by("-date_joined")[:100]
            return render(request, "activity/partials/activity_stat_detail.html", {"users": users})
        elif stat == "new_signups":
            thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
            users = User.objects.filter(date_joined__gte=thirty_days_ago).order_by("-date_joined")[:100]
            return render(request, "activity/partials/activity_stat_detail.html", {"users": users})
        elif stat.isdigit():
            code = int(stat)
            records = qs.filter(status_code=code).select_related("user").order_by("-timestamp")[:100]
            return render(request, "activity/partials/activity_stat_detail.html", {"records": records})
        raise Http404


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
            .order_by("-hits")[:8]
        )

        recent = qs.select_related("user")[:5]
        recent_errors = qs.filter(status_code__gte=300).select_related("user")[:10]

        # User stats
        user_count = User.objects.count()
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        recent_signup_count = User.objects.filter(date_joined__gte=thirty_days_ago).count()

        # Top theme bar (most popular palette, dark/light split)
        palette_choices = [
            (key, label)
            for key, label in UserProfile.COLOR_PALETTE_CHOICES
            if key != ""
        ]
        crosstab_qs = (
            UserProfile.objects.values("theme_preference", "color_palette")
            .annotate(count=Count("pk"))
        )
        counts = {}
        for row in crosstab_qs:
            theme = row["theme_preference"]
            palette = row["color_palette"] or "django"
            counts[(theme, palette)] = (
                counts.get((theme, palette), 0) + row["count"]
            )
        top_theme_bar = None
        best_total = 0
        for pk, label in palette_choices:
            dark = counts.get(("dark", pk), 0)
            light = counts.get(("light", pk), 0)
            total = dark + light
            if total > best_total:
                best_total = total
                top_theme_bar = {
                    "name": label, "dark": dark,
                    "light": light, "total": total,
                }

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
            "recent_errors": recent_errors,
            "user_count": user_count,
            "recent_signup_count": recent_signup_count,
            "top_theme_bar": top_theme_bar,
            "top_users": top_users,
        })
        return context


class RequestListView(StaffRequiredMixin, TemplateView):
    """Staff-only detail view for request logs with htmx-powered tabs."""

    template_name = "activity/requests.html"

    TAB_PARTIALS = {
        "recent": "activity/partials/recent_requests.html",
        "top_paths": "activity/partials/top_paths.html",
        "errors": "activity/partials/errors.html",
        "by_method": "activity/partials/by_method.html",
    }

    def get_tab(self):
        tab = self.request.GET.get("tab", "recent")
        return tab if tab in self.TAB_PARTIALS else "recent"

    def get_status_context(self):
        qs = RequestLog.objects.all()
        total = qs.count()
        status_groups = []
        if total > 0:
            for label, low, high in [("2xx", 200, 300), ("3xx", 300, 400), ("4xx", 400, 500), ("5xx", 500, 600)]:
                count = qs.filter(status_code__gte=low, status_code__lt=high).count()
                if count:
                    status_groups.append({"label": label, "count": count})
        return {"status_groups": status_groups, "total_requests": total}

    page_size = 15

    def get_tab_context(self, tab):
        qs = RequestLog.objects.all()
        if tab == "recent":
            page_obj = paginate_queryset(
                qs.select_related("user").order_by("-timestamp"),
                self.request,
                page_size=self.page_size,
            )
            return {"recent_requests": page_obj, "page_obj": page_obj}
        elif tab == "top_paths":
            page_obj = paginate_queryset(
                qs.values("path")
                .annotate(hits=Count("pk"), avg_time=Avg("response_time_ms"))
                .order_by("-hits"),
                self.request,
                page_size=self.page_size,
            )
            return {"top_paths": page_obj, "page_obj": page_obj}
        elif tab == "errors":
            error_qs = qs.filter(status_code__gte=300)
            last_24h = timezone.now() - timezone.timedelta(hours=24)
            error_counts_24h = (
                error_qs.filter(timestamp__gte=last_24h)
                .values("status_code")
                .annotate(count=Count("pk"))
                .order_by("status_code")
            )
            status_filter = self.request.GET.get("status", "")
            filtered_qs = error_qs
            if status_filter and status_filter.isdigit():
                filtered_qs = error_qs.filter(status_code=int(status_filter))
            page_obj = paginate_queryset(
                filtered_qs.select_related("user").order_by("-timestamp"),
                self.request,
                page_size=self.page_size,
            )
            return {
                "error_counts": error_counts_24h,
                "total_errors_count": error_qs.count(),
                "active_status": status_filter,
                "recent_errors": page_obj,
                "page_obj": page_obj,
            }
        elif tab == "by_method":
            last_24h = timezone.now() - timezone.timedelta(hours=24)
            method_stats = (
                qs.filter(timestamp__gte=last_24h)
                .values("method")
                .annotate(count=Count("pk"), avg_time=Avg("response_time_ms"))
                .order_by("-count")
            )
            method_filter = self.request.GET.get("method", "")
            filtered_qs = qs
            if method_filter:
                filtered_qs = qs.filter(method=method_filter)
            page_obj = paginate_queryset(
                filtered_qs.select_related("user").order_by("-timestamp"),
                self.request,
                page_size=self.page_size,
            )
            total_24h = qs.filter(timestamp__gte=last_24h).count()
            return {
                "method_stats": method_stats,
                "active_method": method_filter,
                "total_requests_count": total_24h,
                "recent_requests": page_obj,
                "page_obj": page_obj,
            }
        return {}

    def get(self, request, *args, **kwargs):
        tab = self.get_tab()
        context = self.get_context_data(**kwargs)
        context.update(self.get_tab_context(tab))
        context["active_tab"] = tab

        if request.htmx:
            return TemplateResponse(
                request, self.TAB_PARTIALS[tab], context
            )

        context.update(self.get_status_context())
        context["tab_partial"] = self.TAB_PARTIALS[tab]
        return TemplateResponse(request, self.template_name, context)


class UserActivityView(StaffRequiredMixin, TemplateView):
    """Staff-only detail view for per-user activity with htmx-powered tabs."""

    template_name = "activity/users.html"
    page_size = 15

    TAB_PARTIALS = {
        "top_users": "activity/partials/user_top_users.html",
        "activity": "activity/partials/user_activity.html",
        "signups": "activity/partials/user_signups.html",
        "inactive": "activity/partials/user_inactive.html",
    }

    def get_tab(self):
        tab = self.request.GET.get("tab", "top_users")
        return tab if tab in self.TAB_PARTIALS else "top_users"

    def get_summary_context(self):
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)

        # Build theme usage bars (horizontal stacked bars per palette)
        # Merge "System Default" (blank) into "Django"
        palette_choices = [
            (key, label)
            for key, label in UserProfile.COLOR_PALETTE_CHOICES
            if key != ""
        ]

        # Query counts grouped by theme + palette
        crosstab_qs = (
            UserProfile.objects.values("theme_preference", "color_palette")
            .annotate(count=Count("pk"))
        )
        counts = {}
        for row in crosstab_qs:
            theme = row["theme_preference"]
            palette = row["color_palette"] or "django"
            counts[(theme, palette)] = (
                counts.get((theme, palette), 0) + row["count"]
            )

        # Build bars sorted by total descending
        theme_bars = []
        for pk, label in palette_choices:
            dark = counts.get(("dark", pk), 0)
            light = counts.get(("light", pk), 0)
            total = dark + light
            if total:
                theme_bars.append({
                    "name": label,
                    "dark": dark,
                    "light": light,
                    "total": total,
                })
        theme_bars.sort(key=lambda b: b["total"], reverse=True)

        return {
            "user_count": User.objects.count(),
            "recent_signup_count": User.objects.filter(
                date_joined__gte=thirty_days_ago
            ).count(),
            "theme_bars": theme_bars,
        }

    def get_tab_context(self, tab):
        if tab == "top_users":
            page_obj = paginate_queryset(
                RequestLog.objects.filter(user__isnull=False)
                .values("user__username", "user__pk")
                .annotate(
                    hits=Count("pk"),
                    avg_time=Avg("response_time_ms"),
                    last_seen=Max("timestamp"),
                )
                .order_by("-hits"),
                self.request,
                page_size=self.page_size,
            )
            return {"top_users": page_obj, "page_obj": page_obj}
        elif tab == "activity":
            page_obj = paginate_queryset(
                RequestLog.objects.filter(user__isnull=False)
                .select_related("user")
                .order_by("-timestamp"),
                self.request,
                page_size=self.page_size,
            )
            return {"recent_user_activity": page_obj, "page_obj": page_obj}
        elif tab == "signups":
            thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
            page_obj = paginate_queryset(
                User.objects.filter(
                    date_joined__gte=thirty_days_ago
                ).order_by("-date_joined"),
                self.request,
                page_size=self.page_size,
            )
            return {"recent_signups": page_obj, "page_obj": page_obj}
        elif tab == "inactive":
            active_user_pks = (
                RequestLog.objects.filter(user__isnull=False)
                .values_list("user__pk", flat=True)
                .distinct()
            )
            page_obj = paginate_queryset(
                User.objects.exclude(pk__in=active_user_pks).order_by("-date_joined"),
                self.request,
                page_size=self.page_size,
            )
            return {"inactive_users": page_obj, "page_obj": page_obj}
        return {}

    def get(self, request, *args, **kwargs):
        tab = self.get_tab()
        context = self.get_context_data(**kwargs)
        context.update(self.get_tab_context(tab))
        context["active_tab"] = tab

        if request.htmx:
            return TemplateResponse(
                request, self.TAB_PARTIALS[tab], context
            )

        context.update(self.get_summary_context())
        context["tab_partial"] = self.TAB_PARTIALS[tab]
        return TemplateResponse(request, self.template_name, context)
