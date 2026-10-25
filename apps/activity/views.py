"""Views for the activity module.

Every page is scoped to a time window (``?window=``, see ``services.WINDOWS``)
and most are htmx-tabbed: a full load renders the page with the active tab's
partial included, an htmx load returns just the partial. The base class
handles both; subclasses declare ``tab_partials`` and fill in
``get_tab_context`` / ``get_page_context``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import TemplateView

from apps.profile.models import UserProfile
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.pagination import paginate_queryset
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from . import services
from .models import RequestLog
from .services import Window

User = get_user_model()

REQUEST_ORDERING = {"timestamp", "method", "path", "status_code", "response_time_ms", "ip_address", "user__username"}
PATH_ORDERING = {"path", "hits", "avg_time", "users", "errors"}


def _is_htmx(request: HttpRequest) -> bool:
    return bool(getattr(request, "htmx", False))


def _theme_bars() -> list[dict[str, Any]]:
    """Palette × theme usage across profiles, most popular first."""
    palette_choices = [(key, label) for key, label in UserProfile.COLOR_PALETTE_CHOICES if key != ""]
    counts: dict[tuple[str, str], int] = {}
    for row in UserProfile.objects.values("theme_preference", "color_palette").annotate(count=Count("pk")):
        pair = (row["theme_preference"], row["color_palette"] or "django")
        counts[pair] = counts.get(pair, 0) + row["count"]
    bars: list[dict[str, Any]] = []
    for palette, label in palette_choices:
        dark = counts.get(("dark", palette), 0)
        light = counts.get(("light", palette), 0)
        if dark + light:
            bars.append({"name": label, "dark": dark, "light": light, "total": dark + light})
    bars.sort(key=lambda b: int(b["total"]), reverse=True)
    return bars


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class ActivityPageView(StaffRequiredMixin, TemplateView):
    """A window-scoped, optionally htmx-tabbed activity page."""

    tab_partials: dict[str, str] = {}
    tabs: list[tuple[str, str]] = []  # (key, label) for the tab bar
    default_tab: str = ""
    page_size = 20
    status_options = ("2xx", "3xx", "4xx", "5xx", "400", "401", "403", "404", "405", "429", "500", "502", "503")
    method_options = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

    @cached_property
    def window(self) -> Window:
        return services.parse_window(self.request)

    @cached_property
    def filters(self) -> services.RequestFilters:
        return services.parse_filters(self.request)

    def base_queryset(self) -> QuerySet[RequestLog]:
        return services.window_queryset(self.window)

    def get_tab(self) -> str:
        tab = self.request.GET.get("tab", self.default_tab)
        return tab if tab in self.tab_partials else self.default_tab

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        return {}

    def get_page_context(self) -> dict[str, Any]:
        """Context only the full page needs (header stats, banners)."""
        return {}

    def request_table(
        self,
        qs: QuerySet[RequestLog],
        *,
        default_ordering: str = "-timestamp",
        cluster_ips: set[str] | None = None,
    ) -> dict[str, Any]:
        """Filter + sort + paginate a request queryset and flag probe rows."""
        qs = services.apply_filters(qs, self.filters)
        ordering = self.request.GET.get("ordering", "").strip()
        qs = qs.select_related("user", "api_token")
        qs = services.apply_ordering(qs, ordering, REQUEST_ORDERING, default_ordering)
        page = paginate_queryset(qs, self.request, page_size=self.page_size)
        rows = services.annotate_probe_flags(list(page.object_list), cluster_ips)
        page.object_list = rows
        return {"page_obj": page, "rows": rows}

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        tab = self.get_tab()
        context = self.get_context_data(**kwargs)
        context.update(
            {
                "window": self.window,
                "windows": list(services.WINDOWS.values()),
                "filters": self.filters,
                "active_tab": tab,
                "tabs": self.tabs,
                "status_options": self.status_options,
                "method_options": self.method_options,
            }
        )
        context.update(self.get_tab_context(tab))
        if _is_htmx(request) and tab in self.tab_partials:
            return TemplateResponse(request, self.tab_partials[tab], context)
        context.update(self.get_page_context())
        if tab in self.tab_partials:
            context["tab_partial"] = self.tab_partials[tab]
        return TemplateResponse(request, self.get_template_names(), context)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class ActivityDashboardView(ActivityPageView):
    """Staff-only overview: headline numbers, the traffic histogram, and the entry points."""

    template_name = "activity/dashboard.html"

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        summary = services.status_summary(qs)
        probes = services.probe_report(qs, self.window, limit=5)
        top_resources = list(services.resource_rollup(qs)[:8])
        top_users = list(services.user_rollup(qs)[:5])
        recent = services.annotate_probe_flags(list(qs.select_related("user")[:10]), set(probes.cluster_ips))
        thirty_days_ago = timezone.now() - timedelta(days=30)
        theme_bars = _theme_bars()
        return {
            "summary": summary,
            "histogram": services.histogram(qs, self.window),
            "probes": probes,
            "top_resources": top_resources,
            "top_users": top_users,
            "recent_requests": recent,
            "user_count": User.objects.count(),
            "recent_signup_count": User.objects.filter(date_joined__gte=thirty_days_ago).count(),
            "top_theme_bar": theme_bars[0] if theme_bars else None,
            "max_rows": getattr(settings, "ACTIVITY_MAX_ROWS", 10000),
            # Kept for templates/tests that read the pre-window names.
            "total_requests": summary.total,
            "avg_response_time": summary.avg_ms,
            "count_4xx": summary.c4xx,
            "count_5xx": summary.c5xx,
            "status_groups": summary.groups,
            "top_paths": top_resources,
        }


class ActivityStatDetailView(StaffRequiredMixin, View):
    """Drill-down bodies for the dashboard stat cards (the global modal).

    The cards reverse a bare URL, so the window is read from htmx's
    ``HX-Current-URL`` header — the page the user is looking at.
    """

    def _window(self, request: HttpRequest) -> Window:
        if request.GET.get("window"):
            return services.parse_window(request)
        current = request.headers.get("HX-Current-URL", "")
        key = parse_qs(urlparse(current).query).get("window", [""])[0]
        return services.WINDOWS.get(key) or services.parse_window(None)

    def get(self, request: HttpRequest, stat: str) -> HttpResponse:
        window = self._window(request)
        qs = services.window_queryset(window)
        detail = "activity/partials/activity_stat_detail.html"

        def table(rows: QuerySet[RequestLog]) -> HttpResponse:
            records = services.annotate_probe_flags(list(rows.select_related("user").order_by("-timestamp")[:100]))
            return render(request, detail, {"records": records})

        if stat == "requests":
            return table(qs)
        if stat == "4xx":
            return table(qs.filter(status_code__gte=400, status_code__lt=500))
        if stat == "5xx":
            return table(qs.filter(status_code__gte=500))
        if stat == "probes":
            report = services.probe_report(qs, window, limit=20)
            return table(services.probe_requests(qs, report))
        if stat == "active_users":
            rows = [
                stat_list_row(
                    r["user__username"],
                    href=reverse("activity:user_detail", args=[r["user__pk"]]) + f"?window={window.key}",
                    avatar=True,
                    meta=f"{r['errors']} error{'s' if r['errors'] != 1 else ''} · avg {int(r['avg_ms'] or 0)} ms",
                    count=r["hits"],
                )
                for r in services.user_rollup(qs)[:100]
            ]
            return render_stat_list(rows, empty=f"No signed-in activity in the {window.label.lower()}.")
        if stat == "users":
            users = User.objects.order_by("-date_joined")[:100]
            return render(request, detail, {"users": users})
        if stat == "new_signups":
            thirty_days_ago = timezone.now() - timedelta(days=30)
            users = User.objects.filter(date_joined__gte=thirty_days_ago).order_by("-date_joined")[:100]
            return render(request, detail, {"users": users})
        if stat.isdigit():
            return table(qs.filter(status_code=int(stat)))
        raise Http404


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class RequestListView(ActivityPageView):
    """The request log: recent traffic, top paths, errors, methods, and probes."""

    template_name = "activity/requests.html"
    default_tab = "recent"
    page_size = 25
    tabs = [
        ("recent", "Recent"),
        ("top_paths", "Top paths"),
        ("errors", "Errors"),
        ("by_method", "By method"),
        ("probes", "Probes"),
    ]
    tab_partials = {
        "recent": "activity/partials/recent_requests.html",
        "top_paths": "activity/partials/top_paths.html",
        "errors": "activity/partials/errors.html",
        "by_method": "activity/partials/by_method.html",
        "probes": "activity/partials/probes.html",
    }

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        qs = self.base_queryset()
        if tab == "recent":
            table = self.request_table(qs)
            return {"recent_requests": table["page_obj"], **table}
        if tab == "top_paths":
            data = qs.values("path").annotate(
                hits=Count("pk"),
                avg_time=Avg("response_time_ms"),
                users=Count("user", distinct=True),
                errors=Count("pk", filter=Q(status_code__gte=400)),
            )
            ordering = self.request.GET.get("ordering", "").strip()
            data = services.apply_ordering(data, ordering, PATH_ORDERING, "-hits")
            page = paginate_queryset(data, self.request, page_size=self.page_size)
            return {"top_paths_list": page, "page_obj": page}
        if tab == "errors":
            error_qs = qs.filter(status_code__gte=400)
            counts = list(error_qs.values("status_code").annotate(count=Count("pk")).order_by("status_code"))
            table = self.request_table(error_qs)
            return {
                "error_counts": counts,
                "total_errors_count": error_qs.count(),
                "active_status": self.filters.status,
                "recent_errors": table["page_obj"],
                **table,
            }
        if tab == "by_method":
            table = self.request_table(qs)
            return {
                "method_stats": services.method_mix(qs),
                "active_method": self.filters.method,
                "total_requests_count": qs.count(),
                "recent_requests": table["page_obj"],
                **table,
            }
        if tab == "probes":
            report = services.probe_report(qs, self.window, limit=20)
            table = self.request_table(services.probe_requests(qs, report), cluster_ips=set(report.cluster_ips))
            return {"probe_report": report, "probe_requests": table["page_obj"], **table}
        return {}

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        summary = services.status_summary(qs)
        return {
            "summary": summary,
            "status_groups": summary.groups,
            "total_requests": summary.total,
            "histogram": services.histogram(qs, self.window),
            "probe_banner": services.probe_report(qs, self.window, limit=5),
        }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


class UserActivityView(ActivityPageView):
    """Who is using the site: per-user roll-up, the signed-in stream, signups, dormancy, preferences."""

    template_name = "activity/users.html"
    default_tab = "top_users"
    tabs = [
        ("top_users", "Top users"),
        ("activity", "Activity"),
        ("signups", "Signups"),
        ("inactive", "Inactive"),
        ("preferences", "Preferences"),
    ]
    tab_partials = {
        "top_users": "activity/partials/user_top_users.html",
        "activity": "activity/partials/user_activity.html",
        "signups": "activity/partials/user_signups.html",
        "inactive": "activity/partials/user_inactive.html",
        "preferences": "activity/partials/user_preferences.html",
    }

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        qs = self.base_queryset()
        since = self.window.since
        if tab == "top_users":
            ordering = self.request.GET.get("ordering", "").strip()
            page = paginate_queryset(services.user_rollup(qs, ordering), self.request, page_size=self.page_size)
            return {"top_users": page, "page_obj": page}
        if tab == "activity":
            table = self.request_table(qs.filter(user__isnull=False))
            return {"recent_user_activity": table["page_obj"], **table}
        if tab == "signups":
            users = User.objects.order_by("-date_joined")
            if since is not None:
                users = users.filter(date_joined__gte=since)
            page = paginate_queryset(users, self.request, page_size=self.page_size)
            return {"recent_signups": page, "page_obj": page}
        if tab == "inactive":
            seen = qs.filter(user__isnull=False).values_list("user__pk", flat=True).distinct()
            users = User.objects.exclude(pk__in=seen)
            if since is not None:
                # Dormant = nothing logged in the window AND no login inside it either.
                users = users.filter(Q(last_login__lt=since) | Q(last_login__isnull=True))
            users = users.order_by("last_login", "-date_joined")
            page = paginate_queryset(users, self.request, page_size=self.page_size)
            return {"inactive_users": page, "page_obj": page}
        if tab == "preferences":
            return {"theme_bars": _theme_bars()}
        return {}

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        summary = services.status_summary(qs)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        return {
            "summary": summary,
            "user_count": User.objects.count(),
            "active_user_count": summary.users,
            "recent_signup_count": User.objects.filter(date_joined__gte=thirty_days_ago).count(),
            "histogram": services.histogram(qs.filter(user__isnull=False), self.window),
        }


class UserDetailView(ActivityPageView):
    """Everything one user did in the window."""

    template_name = "activity/user_detail.html"
    default_tab = "requests"
    tabs = [("requests", "Requests"), ("resources", "Resources"), ("errors", "Errors")]
    tab_partials = {
        "requests": "activity/partials/detail_requests.html",
        "resources": "activity/partials/detail_resources.html",
        "errors": "activity/partials/detail_requests.html",
    }

    @cached_property
    def target(self) -> Any:
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def base_queryset(self) -> QuerySet[RequestLog]:
        return super().base_queryset().filter(user=self.target)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["target"] = self.target
        context["hide_user"] = True
        context["table_key"] = "activity:user-requests"
        return context

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        qs = self.base_queryset()
        if tab == "requests":
            return {"table_title": "Requests", **self.request_table(qs)}
        if tab == "errors":
            return {"table_title": "Errors", **self.request_table(qs.filter(status_code__gte=400))}
        if tab == "resources":
            ordering = self.request.GET.get("ordering", "").strip()
            page = paginate_queryset(services.resource_rollup(qs, ordering), self.request, page_size=self.page_size)
            return {"resources": page, "page_obj": page}
        return {}

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        return {
            "summary": services.status_summary(qs),
            "histogram": services.histogram(qs, self.window),
            "status_mix": services.status_mix(qs)[:6],
            "top_resources": list(services.resource_rollup(qs)[:6]),
            "ips": services.top_values(qs, "ip_address"),
            "agents": services.top_values(qs, "user_agent", limit=3),
            "tokens": list(
                qs.filter(api_token__isnull=False)
                .values("api_token__pk", "api_token__name")
                .annotate(count=Count("pk"))
                .order_by("-count")[:5]
            ),
            "all_time_hits": RequestLog.objects.filter(user=self.target).count(),
        }


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class ResourceListView(ActivityPageView):
    """What is being used: one row per route (or unmatched path)."""

    template_name = "activity/resources.html"
    default_tab = "list"
    page_size = 25
    tab_partials = {"list": "activity/partials/resource_list.html"}

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        qs = self.base_queryset()
        kind = self.request.GET.get("kind", "")
        if kind == "routes":
            qs = qs.exclude(route="")
        elif kind == "unmatched":
            qs = qs.filter(route="")
        ordering = self.request.GET.get("ordering", "").strip()
        rows = services.resource_rollup(qs, ordering)
        if self.filters.q:
            rows = rows.filter(resource__icontains=self.filters.q)
        page = paginate_queryset(rows, self.request, page_size=self.page_size)
        return {"resources": page, "page_obj": page, "kind": kind}

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        summary = services.status_summary(qs)
        return {
            "summary": summary,
            "route_count": qs.exclude(route="").values("route").distinct().count(),
            "unmatched_count": qs.filter(route="").values("path").distinct().count(),
        }


class ResourceDetailView(ActivityPageView):
    """Everything that happened to one resource in the window."""

    template_name = "activity/resource_detail.html"
    default_tab = "requests"
    tabs = [("requests", "Requests"), ("users", "Users"), ("slowest", "Slowest")]
    tab_partials = {
        "requests": "activity/partials/detail_requests.html",
        "users": "activity/partials/detail_users.html",
        "slowest": "activity/partials/detail_requests.html",
    }

    @cached_property
    def resource(self) -> str:
        key = self.request.GET.get("r", "").strip()
        if not key:
            raise Http404("No resource given.")
        return key

    def base_queryset(self) -> QuerySet[RequestLog]:
        return services.for_resource(super().base_queryset(), self.resource)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["resource"] = self.resource
        context["is_route"] = RequestLog.objects.filter(route=self.resource).exists()
        context["tab_extra_qs"] = "r=" + quote(self.resource, safe="")
        context["filter_extra_name"] = "r"
        context["filter_extra_value"] = self.resource
        context["table_key"] = "activity:resource-requests"
        return context

    def get_tab_context(self, tab: str) -> dict[str, Any]:
        qs = self.base_queryset()
        if tab == "requests":
            return {"table_title": "Requests", **self.request_table(qs)}
        if tab == "slowest":
            return {"table_title": "Slowest", **self.request_table(qs, default_ordering="-response_time_ms")}
        if tab == "users":
            ordering = self.request.GET.get("ordering", "").strip()
            page = paginate_queryset(services.user_rollup(qs, ordering), self.request, page_size=self.page_size)
            return {"top_users": page, "page_obj": page}
        return {}

    def get_page_context(self) -> dict[str, Any]:
        qs = self.base_queryset()
        return {
            "summary": services.status_summary(qs),
            "histogram": services.histogram(qs, self.window),
            "status_mix": services.status_mix(qs)[:6],
            "method_mix": services.method_mix(qs),
            "top_users": list(services.user_rollup(qs)[:6]),
            "sample_paths": list(qs.values("path").annotate(hits=Count("pk")).order_by("-hits")[:5]),
            "all_time_hits": services.for_resource(RequestLog.objects.all(), self.resource).count(),
        }
