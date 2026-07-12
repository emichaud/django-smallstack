"""Views for heartbeat status page and dashboard."""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.utils.timezone import get_current_timezone, is_naive, localtime, make_aware, now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin, staff_required
from apps.smallstack.monitors import Monitor
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from .forms import MonitoredEndpointForm, MonitoredSurfaceForm
from .models import Heartbeat, HeartbeatEpoch, MaintenanceWindow, MonitoredEndpoint, MonitoredSurface
from .services import prune_old_heartbeats, run_all_monitors
from .status import (
    _add_sla_context,
    _build_24h_timeline,
    _build_calendar_months,
    _build_daily_timeline,
    _build_maintenance_calendar,
    _build_minute_timeline,
    _calc_overall_uptime,
    _calc_uptime,
    _coverage_since_epoch,
    _get_epoch,
    _get_sla_targets,
    _get_status_data,
    _last_beat_age_seconds,
    _sla_state,
    _upcoming_maintenance,
    build_stacked_timelines,
)

LOCALHOST_IPS = {"127.0.0.1", "::1"}


def _public_status_enabled() -> bool:
    """Whether the anonymous public status surface is turned on (settings flag)."""
    return getattr(settings, "SMALLSTACK_PUBLIC_STATUS_ENABLED", True)


class PublicStatusGateMixin:
    """404 a public-status view when ``SMALLSTACK_PUBLIC_STATUS_ENABLED`` is off.

    Gates at the view (not the URL) so every route pointing at the view is covered
    and ``{% url %}`` references elsewhere never raise NoReverseMatch — they just
    resolve to a 404 page, and the UI hides the links via the context flag.
    """

    def dispatch(self, request, *args, **kwargs):
        if not _public_status_enabled():
            from django.http import Http404

            raise Http404("The public status page is disabled.")
        return super().dispatch(request, *args, **kwargs)


@csrf_exempt
@require_POST
def heartbeat_ping(request: HttpRequest) -> JsonResponse:
    """Localhost-only endpoint for cron to trigger a heartbeat check.

    Replaces ``manage.py heartbeat`` in cron to avoid external-process
    SQLite locking contention — the check runs inside a gunicorn worker.
    """
    remote_ip = request.META.get("REMOTE_ADDR", "")
    if remote_ip not in LOCALHOST_IPS:
        return JsonResponse({"error": "forbidden"}, status=403)

    results = run_all_monitors()
    prune_old_heartbeats()

    # The HTTP status reflects the built-in "site" liveness (the primary signal
    # for cron / load balancers); all monitors' results are in the body.
    site = results.get("site", {})
    status_code = 200 if site.get("status") == "ok" else 503
    return JsonResponse(
        {
            "status": site.get("status", "unknown"),
            "response_time_ms": site.get("response_time_ms", 0),
            "maintenance": site.get("maintenance", False),
            "monitors": {key: r.get("status") for key, r in results.items()},
        },
        status=status_code,
    )


def _verify_partial(ok: bool, message: str) -> HttpResponse:
    """Inline htmx result snippet for the SmallStack-site verify button."""
    cls = "verify-ok" if ok else "verify-bad"
    glyph = "&#10003;" if ok else "&#9888;"
    return HttpResponse(f'<span class="{cls}"><span class="verify-glyph">{glyph}</span>{message}</span>')


@require_POST
@staff_required
def verify_smallstack(request: HttpRequest) -> HttpResponse:
    """Staff-only htmx probe: does ``<url>/health/`` look like a live SmallStack site?

    Non-blocking — purely informational for the Add-monitor wizard. Probes once with
    a short timeout and checks for the SmallStack health JSON shape (``{status,
    database}``). Internal URLs are allowed (staff-gated), mirroring the per-minute
    endpoint checks; add an SSRF allowlist before exposing this to untrusted callers.
    """
    import json
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    raw = (request.POST.get("url") or "").strip().rstrip("/")
    if not raw or urlparse(raw).scheme not in ("http", "https"):
        return _verify_partial(False, "Enter a full URL first, e.g. https://example.com")

    target = raw + "/health/"
    req = urllib.request.Request(target, method="GET", headers={"User-Agent": "smallstack-status-verify"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 — scheme validated above
            code = resp.status
            body = resp.read(4096)
    except urllib.error.HTTPError as exc:
        exc.close()
        return _verify_partial(False, f"/health/ responded HTTP {exc.code} — couldn't verify.")
    except Exception as exc:  # noqa: BLE001 — any transport failure → couldn't verify
        return _verify_partial(False, f"Couldn't reach {target} ({str(exc)[:70]}).")

    if code != 200:
        return _verify_partial(False, f"/health/ responded HTTP {code} — couldn't verify.")
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return _verify_partial(False, "Responded 200, but not JSON — may not be a SmallStack site.")
    if isinstance(data, dict) and "status" in data and "database" in data:
        db = data.get("database")
        return _verify_partial(True, f"Verified — SmallStack /health/ responded 200 (database: {db}).")
    return _verify_partial(False, "Responded 200, but without the SmallStack health shape.")


class StatusPageView(PublicStatusGateMixin, TemplateView):
    """Public, branded status board — no login required.

    A standalone (no admin chrome) page: brand header, an overall status pill, and
    one **90-day daily uptime timeline** per ``public=True`` monitor — the
    Claude-status style the project follows. Internal monitors never appear.
    """

    template_name = "heartbeat/public_status.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack import monitors

        ctx = super().get_context_data(**kwargs)
        brand_name = getattr(settings, "BRAND_NAME", "Site")

        # The primary "site" monitor gets stacked 1-day / 7-day / 90-day timelines;
        # any other public monitors keep a single 90-day row.
        site_timelines: list[dict[str, Any]] = []
        site_state = "unknown"
        rows: list[dict[str, Any]] = []
        states: set[str] = set()
        for monitor in monitors.get_monitors():
            # Public board shows only public, non-orphaned monitors — a monitor whose
            # surface was deregistered isn't a live signal worth publishing.
            if not monitor.public or getattr(monitor, "orphaned", False):
                continue
            data = _get_status_data(monitor.key)
            state = data.get("status", "unknown")
            states.add(state)
            disp = _STATE_DISPLAY.get(state, _STATE_DISPLAY["unknown"])
            if monitor.key == "site":
                site_state = state
                site_timelines = build_stacked_timelines("site")
            else:
                rows.append(
                    {
                        "key": monitor.key,
                        "label": monitor.title,
                        "state": state,
                        "state_label": disp["label"],
                        "variant": disp["variant"],
                        "uptime_90d": _calc_uptime(90 * 24, monitor.key),
                        "timeline": _build_daily_timeline(90, monitor.key),
                    }
                )
        rows.sort(key=lambda r: r["label"])

        if "down" in states:
            overall = "down"
        elif "degraded" in states:
            overall = "degraded"
        elif "maintenance" in states:
            overall = "maintenance"
        elif "operational" in states:
            overall = "operational"
        else:
            overall = "unknown"
        odisp = _STATE_DISPLAY.get(overall, _STATE_DISPLAY["unknown"])

        # Rolling 3-month calendar for the primary (site) monitor — navigable via
        # ?cal=YYYY-MM (the most-recent month shown), defaulting to the current month.
        today = now().date()
        end_year, end_month = today.year, today.month
        cal_param = self.request.GET.get("cal", "")
        if cal_param:
            try:
                y_str, m_str = cal_param.split("-")
                y, m = int(y_str), int(m_str)
                if 1 <= m <= 12:
                    end_year, end_month = y, m
            except (ValueError, IndexError):
                pass
        calendar_months = _build_calendar_months("site", end_year, end_month, months=3)

        def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
            idx = year * 12 + (month - 1) + delta
            return idx // 12, idx % 12 + 1

        cur_idx = today.year * 12 + (today.month - 1)
        end_idx = end_year * 12 + (end_month - 1)
        prev_y, prev_m = _shift(end_year, end_month, -1)
        next_y, next_m = _shift(end_year, end_month, 1)

        ctx.update(
            brand_name=brand_name,
            site_label=brand_name,
            site_state=site_state,
            site_state_label=_STATE_DISPLAY.get(site_state, _STATE_DISPLAY["unknown"])["label"],
            site_timelines=site_timelines,
            monitors=rows,
            overall_state=overall,
            overall_variant=odisp["variant"],
            overall_down_count=(1 if site_state == "down" else 0) + sum(1 for r in rows if r["state"] == "down"),
            overall_degraded_count=(1 if site_state == "degraded" else 0)
            + sum(1 for r in rows if r["state"] == "degraded"),
            overall_maintenance_count=(1 if site_state == "maintenance" else 0)
            + sum(1 for r in rows if r["state"] == "maintenance"),
            calendar_months=calendar_months,
            cal_monitor_label=brand_name,
            cal_range_label=(
                f"{calendar_months[0]['name']} – {calendar_months[-1]['name']}" if calendar_months else ""
            ),
            cal_prev=f"{prev_y:04d}-{prev_m:02d}",
            cal_next=(f"{next_y:04d}-{next_m:02d}" if end_idx < cur_idx else None),
            upcoming_maintenance_count=len(_upcoming_maintenance(90)),
            is_public_view=True,
        )
        return ctx


class PublicMaintenanceView(PublicStatusGateMixin, TemplateView):
    """Public scheduled-maintenance page — in-progress + upcoming windows (next 90 days)."""

    template_name = "heartbeat/public_maintenance.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.smallstack import monitors

        ctx = super().get_context_data(**kwargs)
        brand_name = getattr(settings, "BRAND_NAME", "Site")
        windows = _upcoming_maintenance(90)
        today = now().date()
        for w in windows:
            key = w["monitor_key"]
            if key == "site":
                w["monitor_label"] = brand_name
            else:
                monitor = monitors.get_monitor(key)
                w["monitor_label"] = monitor.title if monitor else key

            # A plain-language "when" so the date reads at a glance.
            days = (w["start"].date() - today).days
            if w["in_progress"]:
                w["when_relative"] = "In progress"
            elif days == 0:
                w["when_relative"] = "Today"
            elif days == 1:
                w["when_relative"] = "Tomorrow"
            elif 2 <= days <= 6:
                w["when_relative"] = w["start"].strftime("%A")  # weekday name
            else:
                w["when_relative"] = f"In {days} days"

            minutes = w["duration_minutes"]
            if minutes >= 60:
                hrs, rem = divmod(minutes, 60)
                w["duration_label"] = f"{hrs} hr" + (f" {rem} min" if rem else "")
            else:
                w["duration_label"] = f"{minutes} min"

        ctx.update(brand_name=brand_name, windows=windows, is_public_view=True)
        return ctx


class PublicMaintenanceCalendarView(PublicStatusGateMixin, TemplateView):
    """Public 6-month maintenance calendar — recent + upcoming windows across all monitors."""

    template_name = "heartbeat/public_maintenance_calendar.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        brand_name = getattr(settings, "BRAND_NAME", "Site")
        months = _build_maintenance_calendar(months_back=2, months_forward=3)
        ctx.update(
            brand_name=brand_name,
            calendar_months=months,
            event_count=sum(m["count"] for m in months),
            range_label=(f"{months[0]['name']} – {months[-1]['name']}" if months else ""),
            is_public_view=True,
        )
        return ctx


@staff_required
def reset_epoch(request: HttpRequest) -> HttpResponse:
    """Staff-only POST endpoint to reset a monitor's monitoring epoch (SLA baseline).

    The target monitor comes from the ``monitor`` POST field (hidden on the SLA
    form), defaulting to ``"site"`` — so the per-monitor SLA editor writes that
    monitor's epoch and leaves the others untouched.
    """
    monitor_key, _ = _resolve_status_monitor(request.POST.get("monitor", "site"))
    if request.method == "POST":
        from .forms import SLAForm

        form = SLAForm(request.POST)
        if form.is_valid():
            started_at = form.cleaned_data["started_at"]
            # datetime-local inputs produce naive datetimes — interpret in
            # the user's active timezone so "2:30 PM EDT" stores correctly.
            if is_naive(started_at):
                started_at = make_aware(started_at, get_current_timezone())
            HeartbeatEpoch.reset(
                monitor_key=monitor_key,
                started_at=started_at,
                service_target=form.cleaned_data["service_target"],
                service_minimum=form.cleaned_data["service_minimum"],
                note=form.cleaned_data.get("note", f"Reset by {request.user.username}"),
            )
    return _sla_redirect(monitor_key)


def _sla_redirect(monitor_key: str) -> HttpResponse:
    """Redirect to the SLA page, preserving the ``?monitor=`` scope for non-site keys."""
    from django.shortcuts import redirect

    resp = redirect("heartbeat:sla")
    if monitor_key and monitor_key != "site":
        resp["Location"] += f"?monitor={monitor_key}"
    return resp


def status_json(request: HttpRequest) -> JsonResponse:
    """Machine-readable public status.

    Shape (two layers, by design):

    - **Top level** (``status``, ``uptime_24h/7d/overall``, ``sla_*``,
      ``monitoring_since``, ``last_heartbeat``) describes the built-in **site**
      monitor only — retained for back-compat with the original public endpoint.
    - **``monitors[]``** is the public status board: one self-contained entry per
      ``public=True`` monitor (orphaned monitors excluded). Prefer this for
      multi-monitor consumers.
    """
    if not _public_status_enabled():
        from django.http import Http404

        raise Http404("The public status page is disabled.")
    data = _get_status_data()
    data["generated_at"] = now().isoformat()
    data["uptime_24h"] = _calc_uptime(24)
    data["uptime_7d"] = _calc_uptime(168)
    data["uptime_overall"] = _calc_overall_uptime()
    target, minimum = _get_sla_targets()
    data["sla_target"] = target
    data["sla_minimum"] = minimum
    epoch = _get_epoch()
    data["monitoring_since"] = epoch.isoformat() if epoch else None
    if data["last_heartbeat"]:
        data["last_heartbeat"] = data["last_heartbeat"].isoformat()

    from apps.smallstack import monitors

    _svc_category = {s.key: s.category for s in monitors.get_services()}
    data["monitors"] = [
        {
            "key": m.key,
            "service": m.service,
            "category": _svc_category.get(m.service, "core"),
            "title": m.title,
            "status": _get_status_data(m.key).get("status", "unknown"),
            "uptime_24h": _calc_uptime(24, m.key),
            "uptime_7d": _calc_uptime(168, m.key),
            "uptime_overall": _calc_overall_uptime(m.key),
        }
        for m in monitors.get_monitors()
        if m.public and not getattr(m, "orphaned", False)
    ]
    return JsonResponse(data)


def _resolve_status_monitor(key: str) -> tuple[str, Monitor | None]:
    """Resolve a ``?monitor=`` key to (monitor_key, Monitor|None), defaulting to site.

    An unknown key falls back to ``"site"`` so the SLA/maintenance editors stay on
    a real monitor rather than 404-ing or writing an orphan epoch.
    """
    from apps.smallstack import monitors

    monitor = monitors.get_monitor(key)
    if monitor is None:
        return "site", monitors.get_monitor("site")
    return key, monitor


class SLADetailView(StaffRequiredMixin, TemplateView):
    """Staff-only SLA detail page with edit form.

    Parameterized by ``?monitor=<key>`` (default ``"site"``): every monitor —
    built-in or user-created endpoint — gets its own SLA targets + maintenance
    windows here, surfacing the per-monitor ``HeartbeatEpoch`` that already exists
    in the data layer. Omitting the param preserves the original site-only page.
    """

    template_name = "heartbeat/sla.html"

    def get_context_data(self, **kwargs):
        from apps.smallstack.pagination import paginate_queryset

        from .forms import SLAForm
        from .models import HeartbeatDaily

        context = super().get_context_data(**kwargs)
        monitor_key, monitor = _resolve_status_monitor(self.request.GET.get("monitor", "site"))
        context["monitor_key"] = monitor_key
        context["monitor"] = monitor
        context["is_site_sla"] = monitor_key == "site"
        context["monitor_title"] = monitor.title if monitor else "Site"

        epoch = _get_epoch(monitor_key)
        context["epoch"] = epoch
        if epoch:
            delta = now() - epoch
            context["monitoring_days"] = delta.days

        context["uptime_overall"] = _calc_overall_uptime(monitor_key)
        context["uptime_24h"] = _calc_uptime(24, monitor_key)
        context["uptime_7d"] = _calc_uptime(168, monitor_key)
        context.update(_get_status_data(monitor_key))
        _add_sla_context(context, monitor_key=monitor_key)

        # Data coverage of the epoch→now span — overall uptime is only as complete
        # as this (uncovered spans count as "no data", not downtime). Surfaced so a
        # coverage gap is visible rather than silently over-reporting.
        coverage = _coverage_since_epoch(monitor_key)
        context["monitoring_coverage"] = round(coverage * 100, 1) if coverage is not None else None

        # Maintenance windows
        context["maintenance_windows"] = MaintenanceWindow.objects.filter(monitor_key=monitor_key)[:50]

        # Daily summaries — the most recent 7 days (a week) per page; pagination
        # keeps older days reachable.
        context["daily_summaries"] = paginate_queryset(
            HeartbeatDaily.objects.filter(monitor_key=monitor_key).order_by("-date"), self.request, page_size=7
        )

        # Pre-fill form with current values (convert epoch to local time
        # so the datetime-local input shows in the user's timezone)
        config = HeartbeatEpoch.get_config(monitor_key)
        initial = {
            "started_at": localtime(epoch) if epoch else localtime(now()),
            "service_target": config.service_target if config else 99.9,
            "service_minimum": config.service_minimum if config else 99.5,
            "note": "",
        }
        context["form"] = SLAForm(initial=initial)

        # Show the active timezone so the user knows how the datetime input is interpreted
        context["form_timezone"] = localtime(now()).strftime("%Z")

        # Downtime allowances for info tooltips
        interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
        context["expected_interval"] = interval
        target = context["sla_target"]
        minimum = context["sla_minimum"]
        monthly_minutes = 30 * 24 * 60
        context["target_down_monthly"] = round((100 - target) / 100 * monthly_minutes, 1)
        context["minimum_down_monthly"] = round((100 - minimum) / 100 * monthly_minutes, 1)

        return context


class HeartbeatDashboardView(StaffRequiredMixin, TemplateView):
    """Staff-only detailed heartbeat dashboard with htmx tabs."""

    template_name = "heartbeat/dashboard.html"
    page_size = 10

    TAB_PARTIALS = {
        "all": "heartbeat/partials/log_table.html",
        "ok": "heartbeat/partials/log_table.html",
        "fail": "heartbeat/partials/log_table.html",
    }

    # Sortable columns for the hand-rolled log table (was HeartbeatTable's
    # Meta.fields when django-tables2 drove sorting pre-v0.12).
    ALLOWED_ORDERING = {"timestamp", "status", "response_time_ms", "note"}

    def get_tab(self):
        tab = self.request.GET.get("tab", "all")
        return tab if tab in self.TAB_PARTIALS else "all"

    def get_ordering(self) -> str:
        """Resolve the ?ordering= param against the allowlist (default -timestamp)."""
        ordering = self.request.GET.get("ordering", "-timestamp").strip()
        if ordering.lstrip("-") in self.ALLOWED_ORDERING:
            return ordering
        return "-timestamp"

    def get_tab_queryset(self, tab):
        qs = Heartbeat.objects.filter(monitor_key="site")
        if tab == "ok":
            qs = qs.filter(status="ok")
        elif tab == "fail":
            qs = qs.filter(status="fail")
        return qs

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator
        from django.db.models import Avg

        context = super().get_context_data(**kwargs)
        tab = self.get_tab()
        context["active_tab"] = tab

        # Heartbeat log for the current tab — hand-rolled table with
        # {% sortable_th %} headers + Django pagination (was HeartbeatTable
        # + django-tables2 RequestConfig pre-v0.12).
        qs = self.get_tab_queryset(tab).order_by(self.get_ordering())
        page_obj = Paginator(qs, self.page_size).get_page(self.request.GET.get("page"))
        # render_paginator's template reads these display helpers.
        page_obj.showing_start = page_obj.start_index()
        page_obj.showing_end = page_obj.end_index()
        page_obj.total_count = page_obj.paginator.count
        context["beats"] = page_obj.object_list
        context["page_obj"] = page_obj
        context["is_paginated"] = page_obj.has_other_pages()

        status_data = _get_status_data()
        context.update(status_data)
        context["uptime_24h"] = _calc_uptime(24)
        context["uptime_7d"] = _calc_uptime(168)
        context["uptime_overall"] = _calc_overall_uptime()
        _add_sla_context(context, use_target=True)

        # Epoch info
        epoch = _get_epoch()
        context["epoch"] = epoch
        if epoch:
            delta = now() - epoch
            context["monitoring_days"] = delta.days

        # Active maintenance indicator
        current = now()
        context["active_maintenance"] = MaintenanceWindow.objects.filter(
            monitor_key="site", start__lte=current, end__gt=current
        ).first()

        context["total_heartbeats"] = Heartbeat.objects.filter(monitor_key="site").count()
        context["ok_count"] = Heartbeat.objects.filter(monitor_key="site", status="ok").count()
        context["fail_count"] = Heartbeat.objects.filter(monitor_key="site", status="fail").count()

        # Config display
        context["retention_days"] = getattr(settings, "HEARTBEAT_RETENTION_DAYS", 7)
        context["expected_interval"] = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)

        # Avg response time
        avg = Heartbeat.objects.filter(monitor_key="site")[:60].aggregate(avg=Avg("response_time_ms"))
        context["avg_response_time"] = round(avg["avg"] or 0)

        # Stat-card display helpers (consumed by {% stat_card %} on the dashboard).
        _status_state = {"operational": "success", "degraded": "warning", "down": "danger"}
        context["status_state"] = _status_state.get(context.get("status"), "muted")
        context["status_card_label"] = "Current Status" + (" · Maint" if context.get("active_maintenance") else "")
        _md = context.get("monitoring_days")
        context["overall_label"] = f"Overall ({_md}d)" if _md else "Overall"
        for key in ("uptime_overall", "uptime_24h", "uptime_7d"):
            val = context.get(key)
            context[f"{key}_display"] = f"{val}%" if val is not None else "—"

        # Timelines (same as status page)
        context["timeline"] = _build_minute_timeline(60)
        context["timeline_24h"] = _build_24h_timeline()

        # Public-style stacked 1d / 7d / 90d uptime bars for the site monitor.
        context["site_timelines"] = build_stacked_timelines("site")

        # JSON status data for the JSON tab
        import json

        json_data = _get_status_data()
        json_data["uptime_24h"] = context["uptime_24h"]
        json_data["uptime_7d"] = context["uptime_7d"]
        json_data["uptime_overall"] = context["uptime_overall"]
        target, minimum = _get_sla_targets()
        json_data["sla_target"] = target
        json_data["sla_minimum"] = minimum
        json_data["monitoring_since"] = epoch.isoformat() if epoch else None
        if json_data.get("last_heartbeat"):
            json_data["last_heartbeat"] = json_data["last_heartbeat"].isoformat()
        context["status_json"] = json.dumps(json_data, indent=2)

        # Overall-health + stale-runner banners (same as the status overview), so
        # the site-timeline page also flags a stopped runner / system-wide outage.
        context.update(_status_overview_context(public_only=False))
        context.update(_runner_health())
        context["is_public_view"] = False

        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        if request.htmx:
            return TemplateResponse(request, self.TAB_PARTIALS[context["active_tab"]], context)

        context["tab_partial"] = self.TAB_PARTIALS[context["active_tab"]]
        # If tab or page params are present, user is in the Heartbeat Log view
        if "tab" in request.GET or "page" in request.GET or "ordering" in request.GET:
            context["active_view"] = "log"
        else:
            context["active_view"] = "timelines"
        return TemplateResponse(request, self.template_name, context)


@staff_required
def heartbeat_incidents(request: HttpRequest) -> HttpResponse:
    """htmx drill-down for the dashboard "Current Status" card: recent failures."""
    fails = Heartbeat.objects.filter(monitor_key="site", status="fail").order_by("-timestamp")[:50]
    rows = [
        stat_list_row(
            localtime(b.timestamp).strftime("%b %d, %H:%M"),
            meta=b.note or "Check failed",
            count=f"{b.response_time_ms} ms" if b.response_time_ms else None,
        )
        for b in fails
    ]
    return render_stat_list(rows, empty="No failures recorded — all clear.")


@staff_required
def maintenance_create(request: HttpRequest) -> HttpResponse | TemplateResponse:
    """Staff-only view to create a maintenance window."""
    from .forms import MaintenanceWindowForm

    monitor_key, monitor = _resolve_status_monitor(request.GET.get("monitor") or request.POST.get("monitor") or "site")

    if request.method == "POST":
        form = MaintenanceWindowForm(request.POST)
        if form.is_valid():
            window = form.save(commit=False)
            window.monitor_key = monitor_key  # scope the window to the selected monitor
            if is_naive(window.start):
                window.start = make_aware(window.start, get_current_timezone())
            if is_naive(window.end):
                window.end = make_aware(window.end, get_current_timezone())
            window.save()
            return _sla_redirect(monitor_key)
    else:
        form = MaintenanceWindowForm()

    return TemplateResponse(
        request,
        "heartbeat/maintenance_form.html",
        {
            "form": form,
            "form_timezone": localtime(now()).strftime("%Z"),
            "editing": False,
            "monitor_key": monitor_key,
            "monitor": monitor,
        },
    )


@staff_required
def maintenance_edit(request: HttpRequest, pk: int) -> HttpResponse | TemplateResponse:
    """Staff-only view to edit a maintenance window."""
    from django.shortcuts import get_object_or_404

    from .forms import MaintenanceWindowForm

    window = get_object_or_404(MaintenanceWindow, pk=pk)

    if request.method == "POST":
        form = MaintenanceWindowForm(request.POST, instance=window)
        if form.is_valid():
            window = form.save(commit=False)
            if is_naive(window.start):
                window.start = make_aware(window.start, get_current_timezone())
            if is_naive(window.end):
                window.end = make_aware(window.end, get_current_timezone())
            window.save()
            return _sla_redirect(window.monitor_key)
    else:
        form = MaintenanceWindowForm(
            instance=window,
            initial={
                "start": localtime(window.start),
                "end": localtime(window.end),
            },
        )

    _, monitor = _resolve_status_monitor(window.monitor_key)
    return TemplateResponse(
        request,
        "heartbeat/maintenance_form.html",
        {
            "form": form,
            "form_timezone": localtime(now()).strftime("%Z"),
            "editing": True,
            "window": window,
            "monitor_key": window.monitor_key,
            "monitor": monitor,
        },
    )


@staff_required
def maintenance_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Staff-only POST endpoint to delete a maintenance window."""
    from django.shortcuts import get_object_or_404, redirect


    if request.method == "POST":
        window = get_object_or_404(MaintenanceWindow, pk=pk)
        monitor_key = window.monitor_key
        window.delete()
        return _sla_redirect(monitor_key)

    return redirect("heartbeat:sla")


# ── Status overview (pluggable monitors) ──────────────────────────────────────

# Display metadata for each liveness state: human label + status_badge variant +
# a non-color glyph (so state survives red/green color-blindness and small dots).
_STATE_DISPLAY: dict[str, dict[str, str]] = {
    "operational": {"label": "Operational", "variant": "success", "glyph": "✓"},
    "degraded": {"label": "Degraded", "variant": "warning", "glyph": "!"},
    "down": {"label": "Down", "variant": "error", "glyph": "×"},
    "unknown": {"label": "No data", "variant": "neutral", "glyph": "–"},
    # An orphaned Site Monitor — its surface was deregistered. Neutral, not alarming:
    # a config change to clean up, never an outage (so it must not roll a tier red).
    "orphaned": {"label": "Not exposed", "variant": "neutral", "glyph": "–"},
    # Active maintenance window — planned work, shown in the accent color so it reads
    # as "heads up", distinct from amber-degraded and red-down. Masks a real outage
    # during the window (a service down on purpose isn't an incident).
    "maintenance": {"label": "Under maintenance", "variant": "info", "glyph": "⚙"},
}
# Severity ordering so a service rolls up to the worst state of its monitors.
# "orphaned" sits at the bottom with operational — it never escalates a tier.
# "maintenance" sits just above operational: it surfaces a window without masquerading
# as degraded/down (a real, non-maintenance problem still wins).
_STATE_SEVERITY: dict[str, int] = {
    "orphaned": 0,
    "operational": 0,
    "maintenance": 1,
    "unknown": 1,
    "degraded": 2,
    "down": 3,
}


def _runner_health() -> dict[str, Any]:
    """Stale-heartbeat self-diagnostic context (staff views only).

    The whole system depends on *something* hitting ``/heartbeat/ping/`` (or
    ``manage.py heartbeat``) every minute. If that isn't wired, every page still
    renders but reads "down"/"warming up" forever — the natural (wrong) read is
    "the feature is broken". This surfaces the real cause: the runner isn't
    running. ``runner_stale`` is set when the freshest beat anywhere is older than
    5× the expected interval; ``runner_never_run`` when there are no beats at all.
    """
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    age = _last_beat_age_seconds()
    return {
        "runner_last_beat_age_seconds": age,
        "runner_last_beat_age_minutes": (age // 60) if age is not None else None,
        "runner_stale": age is not None and age > interval * 5,
        "runner_never_run": age is None,
    }


def _resolve_detail_url(url_name: str | None, kwargs: dict | None) -> str | None:
    """Reverse a monitor/service detail route, returning None if it isn't wired."""
    if not url_name:
        return None
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse(url_name, kwargs=kwargs or {})
    except NoReverseMatch:
        return None


def _monitor_overview_state(monitor: Monitor) -> dict[str, Any]:
    """Resolve a monitor's display state for the overview from its recorded data.

    Reads only the recorded timeseries — pages never run a live ``check()`` (that
    is the runner's job), so rendering can't block on a slow probe or 500 on a
    raising one. A monitor with no beats yet shows "No data" until the next
    runner tick records one. A monitor younger than ``HEARTBEAT_WARMUP_MINUTES``
    is flagged ``warming_up`` so the UI shows a neutral pill instead of a 24h %
    that doesn't yet represent a full window.
    """
    data = _get_status_data(monitor.key)
    known = data.get("status") != "unknown"
    epoch = _get_epoch(monitor.key)
    warmup = timedelta(minutes=getattr(settings, "HEARTBEAT_WARMUP_MINUTES", 60))
    warming_up = bool(epoch) and (now() - epoch) < warmup
    return {
        "state": data.get("status", "unknown"),
        "response_time_ms": data.get("response_time_ms"),
        "uptime_24h": None if warming_up else (_calc_uptime(24, monitor.key) if known else None),
        "warming_up": warming_up,
        "note": "",
    }


class MonitorDetailView(TemplateView):
    """A single monitor's page — composed from the pluggable visualization registry.

    Public-aware: staff see any monitor with every visualization; anonymous /
    non-staff users may only view ``public=True`` monitors (internal ones 404,
    so they aren't even disclosed), and only ``public_safe`` panels render.
    """

    template_name = "heartbeat/monitor_detail.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from django.http import Http404
        from django.template.loader import render_to_string

        from apps.smallstack import monitors, visualizations

        ctx = super().get_context_data(**kwargs)
        monitor_key = self.kwargs["monitor_key"]
        monitor = monitors.get_monitor(monitor_key)
        is_staff = bool(getattr(self.request.user, "is_staff", False))
        if monitor is None or (not is_staff and not monitor.public):
            raise Http404(f"No monitor '{monitor_key}'")
        service = monitors.get_service(monitor.service)

        panels: list[dict[str, Any]] = []
        for viz in visualizations.get_visualizations(public_only=not is_staff):
            html = render_to_string(viz.template, viz.get_context(monitor_key), request=self.request)
            panels.append({"viz": viz, "html": html})

        # Staff get per-monitor management links: SLA targets for any monitor, and
        # an Edit link for user-created endpoint monitors (which have a CRUD row).
        sla_url = edit_url = None
        if is_staff:
            sla_url = _resolve_detail_url("heartbeat:sla", None)
            if sla_url and monitor_key != "site":
                sla_url += f"?monitor={monitor_key}"
            endpoint = getattr(monitor, "endpoint", None)
            if endpoint is not None:
                edit_url = _resolve_detail_url("heartbeat:status/endpoints-update", {"pk": endpoint.pk})

        # Contextual "back to the list" crumb: an endpoint monitor came from the
        # Monitored endpoints list, a surface monitor from Site monitors; everything
        # else just goes back to the Status overview.
        parent_label = parent_url = None
        if getattr(monitor, "endpoint", None) is not None:
            parent_label = "Monitored endpoints"
            parent_url = _resolve_detail_url("heartbeat:status/endpoints-list", None)
        elif getattr(monitor, "surface", None) is not None:
            parent_label = "Site monitors"
            parent_url = _resolve_detail_url("heartbeat:status/site-monitors-list", None)

        state = _monitor_overview_state(monitor)
        ctx.update(
            monitor=monitor,
            service=service,
            panels=panels,
            is_public_view=not is_staff,
            sla_url=sla_url,
            edit_url=edit_url,
            parent_label=parent_label,
            parent_url=parent_url,
            **_STATE_DISPLAY.get(state["state"], _STATE_DISPLAY["unknown"]),
            state=state["state"],
        )
        return ctx


class MonitoredEndpointCRUDView(CRUDView):
    """Create / tag HTTP endpoints to monitor.

    Each enabled row becomes a live monitor via ``endpoint_monitor_source`` and
    shows up on the status overview under the service it's tagged to.

    ``enable_api`` + ``enable_mcp`` apply the headline SmallStack magic to the
    monitoring system's own model: list/create/update/delete a monitor over REST
    or by asking Claude. Writes are auto-gated to staff (the MCP/API factory reads
    the ``StaffRequiredMixin`` below), and ``MonitoredEndpoint.clean()`` is the
    SSRF/service-validation backstop for programmatic callers just as for the form.
    """

    model = MonitoredEndpoint
    namespace = "heartbeat"
    form_class = MonitoredEndpointForm  # service rendered as a <select> of registered services
    fields = ["name", "slug", "service", "url", "method", "expected_status", "timeout_seconds", "enabled", "public"]
    list_fields = ["name", "service", "url", "enabled", "public"]
    detail_fields = [
        "name",
        "slug",
        "service",
        "url",
        "method",
        "expected_status",
        "timeout_seconds",
        "enabled",
        "public",
        "created_at",
    ]
    url_base = "status/endpoints"
    paginate_by = 20
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
    # Root every endpoint CRUD page back at the status hub (the page you arrive from).
    breadcrumb_parent = ("Status", "heartbeat:status_overview")
    # Manage monitors over REST + MCP, not just the HTML form. Writes stay staff-only.
    enable_api = True
    enable_mcp = True
    search_fields = ["name", "slug", "url"]
    filter_fields = ["service", "enabled", "public", "method"]
    ordering_fields = ["name", "created_at"]
    mcp_description = "user-created HTTP endpoint monitors on the status board"

    @classmethod
    def row_link_url(cls, obj, request):
        # Link each row to the monitor's status timeline (not its edit form);
        # the pencil action in the row still goes to edit.
        from django.urls import NoReverseMatch, reverse

        try:
            return reverse("heartbeat:monitor_detail", kwargs={"monitor_key": obj.monitor_key})
        except NoReverseMatch:
            return None


class MonitoredSurfaceCRUDView(CRUDView):
    """Pick / manage Site Monitors — exposed surfaces (API resources, MCP tools).

    The form's surface choice is drawn live from the exposed registry, so you can
    only monitor something the project actually exposes. Each enabled row becomes a
    live monitor via ``surface_monitor_source``; if its surface is later
    deregistered the monitor goes *orphaned* (muted, removable) rather than DOWN.
    """

    model = MonitoredSurface
    namespace = "heartbeat"
    form_class = MonitoredSurfaceForm
    fields = ["name", "kind", "target", "enabled", "public"]
    list_fields = ["name", "kind", "target", "enabled", "public"]
    detail_fields = ["name", "kind", "target", "slug", "enabled", "public", "created_at"]
    url_base = "status/site-monitors"
    paginate_by = 20
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]
    breadcrumb_parent = ("Status", "heartbeat:status_overview")
    search_fields = ["name", "target"]
    filter_fields = ["kind", "enabled", "public"]
    ordering_fields = ["name", "created_at"]

    @classmethod
    def row_link_url(cls, obj, request):
        # Link each row to the monitor's timeline; the pencil action still edits.
        from django.urls import NoReverseMatch, reverse

        try:
            return reverse("heartbeat:monitor_detail", kwargs={"monitor_key": obj.monitor_key})
        except NoReverseMatch:
            return None


def _build_site_card(core_services: list[dict]) -> dict[str, Any]:
    """Build the collapsed Site card: a hero + per-core-service on/off indicators.

    The **hero** is the site monitor's *recorded* history (uptime % since the epoch,
    duration, SLA + Timeline links) — "the server is up, for how long, against its
    SLA". The **core-service rows** use each monitor's *live* ``inventory()`` (an
    in-process registry/connection read) so "is it wired and running" + "what's
    behind it" stay accurate even when the per-minute runner is behind. Database,
    Search, REST API and MCP are all sub-indicators of one Site card, not separate
    SLAs.
    """
    from django.urls import NoReverseMatch, reverse

    services: list[dict[str, Any]] = []
    hero: dict[str, Any] | None = None
    for svc in core_services:
        service = svc["service"]
        rows = svc["monitors"]
        monitor = rows[0]["monitor"] if rows else None
        inv: dict[str, Any] = {"ok": svc["state"] == "operational", "summary": "", "items": []}
        if monitor is not None:
            try:
                inv = monitor.inventory()
            except Exception:  # noqa: BLE001 — a broken inventory can't break the page
                inv = {"ok": False, "summary": "check failed", "items": []}
        ok = bool(inv.get("ok", False))
        display = _STATE_DISPLAY["operational"] if ok else _STATE_DISPLAY["down"]
        services.append(
            {
                "label": service.title,
                "icon": service.icon,
                "ok": ok,
                "state": "operational" if ok else "down",
                "glyph": display["glyph"],
                # "down" (not "off") when a core service isn't operational — there's no
                # per-service toggle, so "off" misreads as "someone disabled this".
                "state_label": "on" if ok else "down",
                "summary": inv.get("summary", ""),
                "items": inv.get("items", []),
                "detail_url": rows[0]["detail_url"]
                if rows
                else _resolve_detail_url(service.detail_url_name, service.detail_url_kwargs),
            }
        )
        if service.key == "site":
            overall = _calc_overall_uptime("site")
            epoch = _get_epoch("site")
            days = (now() - epoch).days if epoch else None

            def _safe_reverse(name: str) -> str | None:
                try:
                    return reverse(name)
                except NoReverseMatch:
                    return None

            hero = {
                "uptime": overall,
                "uptime_display": f"{overall}%" if overall is not None else "—",
                "uptime_24h": _calc_uptime(24, "site"),
                "state": _sla_state(overall, use_target=True, monitor_key="site"),
                "duration_days": days,
                "sla_url": _safe_reverse("heartbeat:sla"),
                "timeline_url": _safe_reverse("heartbeat:dashboard"),
                # One last-hour sparkline for the site — it stands in for the whole card.
                "hour_timeline": _build_minute_timeline(60, "site"),
            }

    # The Site card's header reflects the *live* core state (worst of the on/off
    # indicators), so it can't contradict its own rows when the recorded heartbeat
    # is stale — "everything's wired and running" reads green even mid-outage of the
    # runner. (The hero uptime % stays the historical SLA figure.)
    oks = [s["ok"] for s in services]
    if not services:
        live_state = "unknown"
    elif all(oks):
        live_state = "operational"
    elif any(oks):
        live_state = "degraded"
    else:
        live_state = "down"
    return {"hero": hero, "services": services, "state": live_state}


def _status_overview_context(public_only: bool = False) -> dict[str, Any]:
    """Build the services/monitors overview context.

    ``public_only=True`` drops non-public monitors (and services left with none) —
    the public ``/status/`` board. The staff overview passes ``False`` and shows
    every service, including empty ones.
    """
    from apps.smallstack import monitors

    # Fetch all monitors once (each dynamic source runs a query) and group by
    # service, rather than calling get_monitors(service) per service (N+1).
    by_service: dict[str, list] = {}
    for monitor in monitors.get_monitors():
        if public_only and not monitor.public:
            continue
        by_service.setdefault(monitor.service, []).append(monitor)

    services: list[dict[str, Any]] = []
    for service in monitors.get_services():
        mons = by_service.get(service.key, [])
        if public_only and not mons:
            continue  # no public monitors → hide the service publicly
        rows: list[dict[str, Any]] = []
        worst = "operational"
        for monitor in mons:
            state = _monitor_overview_state(monitor)
            display = _STATE_DISPLAY.get(state["state"], _STATE_DISPLAY["unknown"])
            rows.append(
                {
                    "monitor": monitor,
                    "detail_url": _resolve_detail_url(monitor.detail_url_name, monitor.detail_url_kwargs),
                    **state,
                    **display,
                }
            )
            if _STATE_SEVERITY.get(state["state"], 1) > _STATE_SEVERITY.get(worst, 0):
                worst = state["state"]
        services.append(
            {
                "service": service,
                "monitors": rows,
                "state": worst,
                **_STATE_DISPLAY.get(worst, _STATE_DISPLAY["unknown"]),
            }
        )

    # Roll every monitor up to one overall state for the at-a-glance health banner
    # (the single most-scannable signal). Precedence down > degraded > operational
    # > unknown: a real problem wins, but "no data yet" never masquerades as green.
    all_rows = [r for s in services for r in s["monitors"]]
    states = {r["state"] for r in all_rows}
    if "down" in states:
        overall_state = "down"
    elif "degraded" in states:
        overall_state = "degraded"
    elif "maintenance" in states:
        overall_state = "maintenance"
    elif "operational" in states:
        overall_state = "operational"
    else:
        overall_state = "unknown"

    # Group the per-service cards into the three overview tiers (Site / Site Monitors
    # / External Monitors), each with its own worst-state roll-up. `services` etc. are
    # kept intact below — `categories` is purely additive (the dashboard banners read
    # `overall_*`). Public board: `services` already excludes empty services, so empty
    # tiers fall away naturally; staff sees empty tiers (with a hint) for discoverability.
    by_category: dict[str, list] = {}
    for svc in services:
        by_category.setdefault(svc["service"].category, []).append(svc)
    categories: list[dict[str, Any]] = []
    for cat_key in sorted(by_category, key=lambda k: monitors.CATEGORY_ORDER.get(k, 99)):
        cat_services = by_category[cat_key]
        cat_rows = [r for s in cat_services for r in s["monitors"]]
        cat_states = {r["state"] for r in cat_rows}
        if "down" in cat_states:
            cat_state = "down"
        elif "degraded" in cat_states:
            cat_state = "degraded"
        elif "maintenance" in cat_states:
            cat_state = "maintenance"
        elif "operational" in cat_states:
            cat_state = "operational"
        else:
            cat_state = "unknown"
        # Flatten each tier into compact "surface" rows for a single collapsed card.
        # Core surfaces ARE the services (one rolled-up row each — drilling in shows
        # the checks); the user tiers (external/internal) list one row per monitor,
        # since there each monitor is itself a distinct surface.
        display_rows: list[dict[str, Any]] = []
        for svc in cat_services:
            mons = svc["monitors"]
            if cat_key == "core":
                if not mons:
                    continue
                single = len(mons) == 1
                rep = mons[0] if single else max(mons, key=lambda r: _STATE_SEVERITY.get(r["state"], 1))
                display_rows.append(
                    {
                        "label": svc["service"].title,
                        "icon": svc["service"].icon,
                        "state": svc["state"],
                        "glyph": svc["glyph"],
                        "state_label": svc["label"],
                        "detail_url": rep["detail_url"],
                        "uptime_24h": rep["uptime_24h"] if single else None,
                        "response_time_ms": rep["response_time_ms"] if single else None,
                        "warming_up": rep["warming_up"] if single else False,
                        "note": rep.get("note", ""),
                        "internal": not svc["service"].public,
                        "check_count": len(mons),
                    }
                )
            else:
                for r in mons:
                    monitor = r["monitor"]
                    # An orphaned Site Monitor renders muted with a Remove prompt and
                    # no live stats — its surface is gone, so its recorded uptime is
                    # meaningless. Everything else uses its recorded state.
                    orphaned = getattr(monitor, "orphaned", False)
                    disp = _STATE_DISPLAY["orphaned"] if orphaned else r
                    remove_url = None
                    if orphaned:
                        surface = getattr(monitor, "surface", None)
                        if surface is not None:
                            remove_url = _resolve_detail_url(
                                "heartbeat:status/site-monitors-delete", {"pk": surface.pk}
                            )
                    display_rows.append(
                        {
                            "label": monitor.title,
                            "icon": svc["service"].icon,
                            "state": "orphaned" if orphaned else r["state"],
                            "glyph": disp["glyph"],
                            "state_label": _STATE_DISPLAY["orphaned"]["label"] if orphaned else r["label"],
                            "detail_url": None if orphaned else r["detail_url"],
                            "uptime_24h": None if orphaned else r["uptime_24h"],
                            "response_time_ms": None if orphaned else r["response_time_ms"],
                            "warming_up": False if orphaned else r["warming_up"],
                            "note": "no longer exposed" if orphaned else r.get("note", ""),
                            "internal": not monitor.public,
                            "check_count": 1,
                            "orphaned": orphaned,
                            "remove_url": remove_url,
                            # Per-row last-hour sparkline (orphaned rows have no live data).
                            "hour_timeline": None if orphaned else _build_minute_timeline(60, monitor.key),
                        }
                    )

        # The core (Site) tier's header badge follows the live core state from the
        # Site card; other tiers follow their recorded heartbeat roll-up.
        site_card = _build_site_card(cat_services) if cat_key == "core" else None
        if site_card:
            cat_state = site_card["state"]
        disp = _STATE_DISPLAY.get(cat_state, _STATE_DISPLAY["unknown"])
        categories.append(
            {
                "key": cat_key,
                "label": monitors.CATEGORY_LABELS.get(cat_key, cat_key.title()),
                "order": monitors.CATEGORY_ORDER.get(cat_key, 99),
                "services": cat_services,
                "rows": display_rows,
                "site_card": site_card,
                "monitor_count": len(cat_rows),
                "hint": monitors.CATEGORY_HINTS.get(cat_key, ""),
                "state": cat_state,
                "state_label": disp["label"],  # e.g. "Operational" (distinct from the tier label)
                "variant": disp["variant"],
                "glyph": disp["glyph"],
            }
        )

    return {
        "services": services,
        "categories": categories,
        "service_count": len(services),
        "monitor_count": len(all_rows),
        "overall_state": overall_state,
        "overall_down_count": sum(1 for r in all_rows if r["state"] == "down"),
        "overall_degraded_count": sum(1 for r in all_rows if r["state"] == "degraded"),
        "overall_maintenance_count": sum(1 for r in all_rows if r["state"] == "maintenance"),
        **{f"overall_{k}": v for k, v in _STATE_DISPLAY.get(overall_state, _STATE_DISPLAY["unknown"]).items()},
    }


class StatusOverviewView(StaffRequiredMixin, TemplateView):
    """Staff consolidated overview of every registered service and its monitors."""

    template_name = "heartbeat/status_overview.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx.update(_status_overview_context(public_only=False))
        ctx.update(_runner_health())  # staff-only stale-heartbeat diagnostic
        ctx["is_public_view"] = False
        return ctx
