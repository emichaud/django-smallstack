"""Views for heartbeat status page and dashboard."""

from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils.timezone import get_current_timezone, is_naive, localtime, make_aware, now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.mixins import StaffRequiredMixin

from .models import Heartbeat, HeartbeatEpoch, MaintenanceWindow
from .services import prune_old_heartbeats, run_heartbeat_check

LOCALHOST_IPS = {"127.0.0.1", "::1"}


@csrf_exempt
@require_POST
def heartbeat_ping(request):
    """Localhost-only endpoint for cron to trigger a heartbeat check.

    Replaces ``manage.py heartbeat`` in cron to avoid external-process
    SQLite locking contention — the check runs inside a gunicorn worker.
    """
    remote_ip = request.META.get("REMOTE_ADDR", "")
    if remote_ip not in LOCALHOST_IPS:
        return JsonResponse({"error": "forbidden"}, status=403)

    result = run_heartbeat_check()
    prune_old_heartbeats()

    status_code = 200 if result["status"] == "ok" else 503
    return JsonResponse(
        {
            "status": result["status"],
            "response_time_ms": result["response_time_ms"],
            "maintenance": result["maintenance"],
        },
        status=status_code,
    )


def _get_epoch():
    """Return the monitoring epoch, or None."""
    return HeartbeatEpoch.get_epoch()


def _get_sla_targets():
    """Return (service_target, service_minimum) as floats."""
    return HeartbeatEpoch.get_sla_targets()


def _sla_color(uptime_pct, use_target=False):
    """Return a CSS color variable based on uptime vs SLA thresholds.

    With use_target=True (dashboard): green >= target, yellow >= minimum, red < minimum.
    With use_target=False (default): green >= minimum, red < minimum.
    """
    if uptime_pct is None:
        return "var(--body-quiet-color)"
    target, minimum = _get_sla_targets()
    if use_target:
        if uptime_pct >= target:
            return "var(--success-fg)"
        elif uptime_pct >= minimum:
            return "var(--warning-fg)"
        else:
            return "var(--error-fg)"
    else:
        if uptime_pct >= minimum:
            return "var(--success-fg)"
        else:
            return "var(--error-fg)"


def _get_status_data():
    """Compute current status from recent heartbeats."""
    expected_interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    recent = list(Heartbeat.objects.all()[:5])

    if not recent:
        return {
            "status": "unknown",
            "status_label": "No Data",
            "last_heartbeat": None,
            "response_time_ms": 0,
        }

    last = recent[0]
    age_seconds = (now() - last.timestamp).total_seconds()

    # Determine status
    if last.status == "fail" or age_seconds > expected_interval * 5:
        status = "down"
        status_label = "Down"
    elif any(h.status == "fail" for h in recent):
        status = "degraded"
        status_label = "Degraded"
    else:
        status = "operational"
        status_label = "Operational"

    return {
        "status": status,
        "status_label": status_label,
        "last_heartbeat": last.timestamp,
        "response_time_ms": last.response_time_ms,
        "age_seconds": int(age_seconds),
    }


def _get_non_maintenance_ok_count(window_start, window_end):
    """Count OK beats excluding those within SLA-excluded maintenance windows."""
    excluded_ranges = MaintenanceWindow.get_excluded_ranges(window_start, window_end)
    qs = Heartbeat.objects.filter(timestamp__gte=window_start, timestamp__lt=window_end, status="ok")
    for s, e in excluded_ranges:
        qs = qs.exclude(timestamp__gte=s, timestamp__lt=e)
    return qs.count()


def _calc_uptime(hours):
    """Calculate uptime percentage over the given window, epoch-aware.

    Expected checks are floored to complete intervals — the current
    incomplete minute doesn't count against uptime. Maintenance windows
    with exclude_from_sla=True are subtracted from both numerator and
    denominator.
    """
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    epoch = _get_epoch()
    current = now()
    window_start = current - timedelta(hours=hours)

    if epoch and window_start < epoch:
        window_start = epoch

    elapsed_seconds = (current - window_start).total_seconds()
    if elapsed_seconds <= 0:
        return None

    excluded_seconds = MaintenanceWindow.get_excluded_seconds(window_start, current)
    effective_seconds = elapsed_seconds - excluded_seconds
    if effective_seconds <= 0:
        return None

    expected = int(effective_seconds // interval)
    if expected < 1:
        return None

    ok_count = _get_non_maintenance_ok_count(window_start, current)

    return min(round((ok_count / expected) * 100, 2), 100.0)


def _calc_overall_uptime():
    """Calculate uptime since the epoch.

    Expected checks are floored to complete intervals — the current
    incomplete minute doesn't count against uptime. Maintenance windows
    with exclude_from_sla=True are subtracted from both numerator and
    denominator.
    """
    interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
    epoch = _get_epoch()
    if not epoch:
        return None

    current = now()
    elapsed_seconds = (current - epoch).total_seconds()
    if elapsed_seconds <= 0:
        return None

    excluded_seconds = MaintenanceWindow.get_excluded_seconds(epoch, current)
    effective_seconds = elapsed_seconds - excluded_seconds
    if effective_seconds <= 0:
        return None

    expected = int(effective_seconds // interval)
    if expected < 1:
        return None

    ok_count = _get_non_maintenance_ok_count(epoch, current)

    return min(round((ok_count / expected) * 100, 2), 100.0)


def _add_sla_context(context, use_target=False):
    """Add SLA targets and color info to a template context.

    use_target=True: 3-tier coloring (green/yellow/red) for dashboard.
    use_target=False: 2-tier coloring (green/red vs minimum) for public/SLA pages.
    """
    target, minimum = _get_sla_targets()
    context["sla_target"] = target
    context["sla_minimum"] = minimum

    # Color each uptime value
    for key in ("uptime_overall", "uptime_24h", "uptime_7d"):
        val = context.get(key)
        context[f"{key}_color"] = _sla_color(val, use_target=use_target)

    return context


def _is_in_any_window(dt, windows):
    """Check if a datetime falls within any of the given (start, end) tuples."""
    for ws, we in windows:
        if ws <= dt < we:
            return True
    return False


def _build_minute_timeline(minutes=60):
    """Build a slot-based timeline for the last N minutes."""
    current = now()
    epoch = _get_epoch()
    cutoff = current - timedelta(minutes=minutes)

    beats = list(
        Heartbeat.objects.filter(timestamp__gte=cutoff)
        .order_by("timestamp")
        .values("status", "timestamp", "response_time_ms")
    )

    maint_windows = list(
        MaintenanceWindow.objects.filter(start__lt=current, end__gt=cutoff).values_list("start", "end")
    )

    slots = []
    for i in range(minutes):
        slot_start = cutoff + timedelta(minutes=i)
        slot_end = slot_start + timedelta(minutes=1)

        if epoch and slot_end <= epoch:
            slots.append(
                {
                    "status": "pre-epoch",
                    "timestamp": slot_start,
                    "response_time_ms": 0,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
            continue

        in_maintenance = _is_in_any_window(slot_start, maint_windows)
        slot_beats = [b for b in beats if slot_start <= b["timestamp"] < slot_end]

        if in_maintenance:
            avg_ms = 0
            if slot_beats:
                avg_ms = sum(b["response_time_ms"] for b in slot_beats) // len(slot_beats)
            slots.append(
                {
                    "status": "maintenance",
                    "timestamp": slot_start,
                    "response_time_ms": avg_ms,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
        elif slot_beats:
            has_fail = any(b["status"] == "fail" for b in slot_beats)
            avg_ms = sum(b["response_time_ms"] for b in slot_beats) // len(slot_beats)
            slots.append(
                {
                    "status": "fail" if has_fail else "ok",
                    "timestamp": slot_beats[0]["timestamp"],
                    "response_time_ms": avg_ms,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )
        else:
            slots.append(
                {
                    "status": "missed",
                    "timestamp": slot_start,
                    "response_time_ms": 0,
                    "label": localtime(slot_start).strftime("%-I:%M %p"),
                }
            )

    return slots


def _build_24h_timeline():
    """Build a 24-hour timeline grouped into 15-minute buckets."""
    current = now()
    epoch = _get_epoch()
    cutoff = current - timedelta(hours=24)

    beats = list(Heartbeat.objects.filter(timestamp__gte=cutoff).order_by("timestamp").values("status", "timestamp"))

    maint_windows = list(
        MaintenanceWindow.objects.filter(start__lt=current, end__gt=cutoff).values_list("start", "end")
    )

    slots = []
    for i in range(96):
        slot_start = cutoff + timedelta(minutes=i * 15)
        slot_end = slot_start + timedelta(minutes=15)

        if epoch and slot_end <= epoch:
            slots.append(
                {
                    "status": "pre-epoch",
                    "ok_count": 0,
                    "fail_count": 0,
                    "total": 0,
                    "hour_label": localtime(slot_start).strftime("%-I:%M %p"),
                    "timestamp": slot_start,
                }
            )
            continue

        in_maintenance = any(ws < slot_end and we > slot_start for ws, we in maint_windows)

        slot_beats = [b for b in beats if slot_start <= b["timestamp"] < slot_end]
        ok_count = sum(1 for b in slot_beats if b["status"] == "ok")
        fail_count = sum(1 for b in slot_beats if b["status"] == "fail")
        total = len(slot_beats)

        if in_maintenance:
            status = "maintenance"
        elif total == 0:
            status = "missed"
        elif fail_count > 0 and ok_count > 0:
            status = "partial"
        elif fail_count > 0:
            status = "fail"
        else:
            status = "ok"

        slots.append(
            {
                "status": status,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "total": total,
                "hour_label": localtime(slot_start).strftime("%-I:%M %p"),
                "timestamp": slot_start,
            }
        )

    return slots


class StatusPageView(TemplateView):
    """Public status page — no login required."""

    template_name = "heartbeat/status.html"

    def get_context_data(self, **kwargs):
        from django.db.models import Avg

        context = super().get_context_data(**kwargs)
        status_data = _get_status_data()
        context.update(status_data)
        context["uptime_24h"] = _calc_uptime(24)
        context["uptime_7d"] = _calc_uptime(168)
        context["uptime_overall"] = _calc_overall_uptime()

        # Epoch info
        epoch = _get_epoch()
        context["epoch"] = epoch
        if epoch:
            delta = now() - epoch
            context["monitoring_days"] = delta.days

        # SLA colors (public page uses minimum threshold)
        _add_sla_context(context)

        # Slot-based timelines
        context["timeline"] = _build_minute_timeline(60)
        context["timeline_24h"] = _build_24h_timeline()

        # Average response time (last 60)
        avg = Heartbeat.objects.all()[:60].aggregate(avg=Avg("response_time_ms"))
        context["avg_response_time"] = round(avg["avg"] or 0)

        # Maintenance banners
        current = now()
        context["active_maintenance"] = MaintenanceWindow.objects.filter(start__lte=current, end__gt=current).first()
        context["upcoming_maintenance"] = (
            MaintenanceWindow.objects.filter(start__gt=current, start__lte=current + timedelta(hours=24))
            .order_by("start")
            .first()
        )

        return context


def reset_epoch(request):
    """Staff-only POST endpoint to reset the monitoring epoch (SLA baseline)."""
    from django.shortcuts import redirect

    if not request.user.is_staff:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden()
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
                started_at=started_at,
                service_target=form.cleaned_data["service_target"],
                service_minimum=form.cleaned_data["service_minimum"],
                note=form.cleaned_data.get("note", f"Reset by {request.user.username}"),
            )
    return redirect("heartbeat:sla")


def status_json(request):
    """Machine-readable JSON status endpoint."""
    data = _get_status_data()
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
    return JsonResponse(data)


class SLADetailView(StaffRequiredMixin, TemplateView):
    """Staff-only SLA detail page with edit form."""

    template_name = "heartbeat/sla.html"

    def get_context_data(self, **kwargs):
        from .forms import SLAForm
        from .models import HeartbeatDaily

        context = super().get_context_data(**kwargs)
        epoch = _get_epoch()
        context["epoch"] = epoch
        if epoch:
            delta = now() - epoch
            context["monitoring_days"] = delta.days

        context["uptime_overall"] = _calc_overall_uptime()
        context["uptime_24h"] = _calc_uptime(24)
        context["uptime_7d"] = _calc_uptime(168)
        context.update(_get_status_data())
        _add_sla_context(context)

        # Maintenance windows
        context["maintenance_windows"] = MaintenanceWindow.objects.all()[:50]

        # Daily summaries for long-term view
        context["daily_summaries"] = HeartbeatDaily.objects.all()[:30]

        # Pre-fill form with current values (convert epoch to local time
        # so the datetime-local input shows in the user's timezone)
        config = HeartbeatEpoch.get_config()
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

    def get_tab(self):
        tab = self.request.GET.get("tab", "all")
        return tab if tab in self.TAB_PARTIALS else "all"

    def get_tab_queryset(self, tab):
        qs = Heartbeat.objects.all()
        if tab == "ok":
            qs = qs.filter(status="ok")
        elif tab == "fail":
            qs = qs.filter(status="fail")
        return qs

    def get_context_data(self, **kwargs):
        from django.db.models import Avg
        from django_tables2 import RequestConfig

        from .tables import HeartbeatTable

        context = super().get_context_data(**kwargs)
        tab = self.get_tab()
        context["active_tab"] = tab

        # Table for current tab
        qs = self.get_tab_queryset(tab)
        table = HeartbeatTable(qs)
        RequestConfig(self.request, paginate={"per_page": self.page_size}).configure(table)
        context["table"] = table

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
        context["active_maintenance"] = MaintenanceWindow.objects.filter(start__lte=current, end__gt=current).first()

        context["total_heartbeats"] = Heartbeat.objects.count()
        context["ok_count"] = Heartbeat.objects.filter(status="ok").count()
        context["fail_count"] = Heartbeat.objects.filter(status="fail").count()

        # Config display
        context["retention_days"] = getattr(settings, "HEARTBEAT_RETENTION_DAYS", 7)
        context["expected_interval"] = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)

        # Avg response time
        avg = Heartbeat.objects.all()[:60].aggregate(avg=Avg("response_time_ms"))
        context["avg_response_time"] = round(avg["avg"] or 0)

        # Timelines (same as status page)
        context["timeline"] = _build_minute_timeline(60)
        context["timeline_24h"] = _build_24h_timeline()

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

        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        if request.htmx:
            return TemplateResponse(request, self.TAB_PARTIALS[context["active_tab"]], context)

        context["tab_partial"] = self.TAB_PARTIALS[context["active_tab"]]
        # If tab or page params are present, user is in the Heartbeat Log view
        if "tab" in request.GET or "page" in request.GET or "sort" in request.GET:
            context["active_view"] = "log"
        else:
            context["active_view"] = "timelines"
        return TemplateResponse(request, self.template_name, context)


def maintenance_create(request):
    """Staff-only view to create a maintenance window."""
    from django.shortcuts import redirect

    from .forms import MaintenanceWindowForm

    if not request.user.is_staff:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden()

    if request.method == "POST":
        form = MaintenanceWindowForm(request.POST)
        if form.is_valid():
            window = form.save(commit=False)
            if is_naive(window.start):
                window.start = make_aware(window.start, get_current_timezone())
            if is_naive(window.end):
                window.end = make_aware(window.end, get_current_timezone())
            window.save()
            return redirect("heartbeat:sla")
    else:
        form = MaintenanceWindowForm()

    return TemplateResponse(
        request,
        "heartbeat/maintenance_form.html",
        {
            "form": form,
            "form_timezone": localtime(now()).strftime("%Z"),
            "editing": False,
        },
    )


def maintenance_edit(request, pk):
    """Staff-only view to edit a maintenance window."""
    from django.shortcuts import get_object_or_404, redirect

    from .forms import MaintenanceWindowForm

    if not request.user.is_staff:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden()

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
            return redirect("heartbeat:sla")
    else:
        form = MaintenanceWindowForm(
            instance=window,
            initial={
                "start": localtime(window.start),
                "end": localtime(window.end),
            },
        )

    return TemplateResponse(
        request,
        "heartbeat/maintenance_form.html",
        {
            "form": form,
            "form_timezone": localtime(now()).strftime("%Z"),
            "editing": True,
            "window": window,
        },
    )


def maintenance_delete(request, pk):
    """Staff-only POST endpoint to delete a maintenance window."""
    from django.shortcuts import get_object_or_404, redirect

    if not request.user.is_staff:
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden()

    if request.method == "POST":
        window = get_object_or_404(MaintenanceWindow, pk=pk)
        window.delete()

    return redirect("heartbeat:sla")
