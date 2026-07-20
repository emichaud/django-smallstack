"""Scheduler views — CRUDView, dashboard, the tick endpoint, and run-now."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import CalendarDisplay, FormDisplay, TableDisplay
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from . import schedules, services
from .forms import ScheduledJobForm
from .models import ScheduledJob, ScheduledJobRun

LOCALHOST_IPS = {"127.0.0.1", "::1"}


def _status_badge(value: str | None, obj: ScheduledJob) -> str:
    """Colored last-status pill for the list view."""
    from django.utils.html import format_html

    color = {
        "queued": "var(--body-quiet-color)",
        "success": "var(--success-fg)",
        "failed": "var(--error-fg)",
        "skipped": "var(--warning-fg)",
        "invalid": "var(--error-fg)",
    }.get(value or "", "var(--body-quiet-color)")
    label = value or "—"
    return format_html('<span style="color: {};">{}</span>', color, label)


def _cadence(value: str | None, obj: ScheduledJob) -> str:
    return obj.cadence_display


def _compact_dt(value: Any, obj: Any) -> Any:
    """Compact local datetime for table cells. Returning our own string bypasses
    the default long datetime render + click-to-preview truncation."""
    from datetime import datetime as _dt

    if not isinstance(value, _dt):
        return value  # already "—" for None
    return timezone.localtime(value).strftime("%b %-d, %-I:%M %p")


def _run_status_badge(value: Any, obj: Any) -> Any:
    """Colour a run's status. Reads obj.status (raw) since the cell value has
    already been run through get_status_display() for the choice field."""
    from django.utils.html import format_html

    color = {
        "queued": "var(--body-quiet-color)",
        "success": "var(--success-fg)",
        "failed": "var(--error-fg)",
        "skipped": "var(--warning-fg)",
    }.get(obj.status, "var(--body-quiet-color)")
    return format_html('<span style="color: {};">{}</span>', color, value)


def _humanize_delta(dt: datetime) -> str:
    secs = int((dt - timezone.now()).total_seconds())
    if secs < 0:
        return "now"
    if secs < 3600:
        return f"in {secs // 60}m"
    if secs < 86400:
        return f"in {secs // 3600}h {secs % 3600 // 60}m"
    return f"in {secs // 86400}d"


@require_POST
def scheduler_preview(request: HttpRequest) -> HttpResponse:
    """htmx endpoint — the next 5 fire times for the cadence being edited.

    Builds a throwaway ScheduledJob from just the cadence fields (so it works
    before the whole form is valid) and walks compute_next_run.
    """
    if not request.user.is_staff:
        return HttpResponse(status=403)

    def _dt(name: str) -> datetime | None:
        raw = (request.POST.get(name) or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

    inst = ScheduledJob(
        schedule_type=request.POST.get("schedule_type") or "",
        interval_spec=(request.POST.get("interval_spec") or "").strip(),
        cron_expression=(request.POST.get("cron_expression") or "").strip(),
        run_at=_dt("run_at"),
        anchor_at=_dt("anchor_at"),
        timezone=(request.POST.get("timezone") or "").strip(),
    )
    runs: list[dict] = []
    error = None
    after = timezone.now()
    try:
        for _ in range(5):
            nxt = inst.compute_next_run(after=after)
            if nxt is None:
                break
            runs.append({"abs": nxt.strftime("%a, %b %-d · %-I:%M %p"), "rel": _humanize_delta(nxt)})
            after = nxt
    except schedules.ScheduleConfigError as exc:
        error = str(exc)
    except Exception:
        error = "Enter a valid cadence to preview runs."
    return render(request, "scheduler/crud/_preview_runs.html", {"runs": runs, "error": error})


class ScheduledJobFormDisplay(FormDisplay):
    """Visual cadence editor: segmented schedule-type picker with progressive
    disclosure, an interval builder, and a cron builder narrated by a live
    plain-English summary. The real form inputs stay the source of truth."""

    name = "scheduler"
    template_name = "scheduler/crud/form_scheduler.html"
    show_palette = False


class ScheduledJobCRUDView(CRUDView):
    """Themed list/detail/create/update for schedules — plus REST + MCP.

    Schedules are data an operator (or an AI agent) manages, so both API and
    MCP surfaces are on: an agent can list schedules, pause one, or create a
    recurring job through the same audited path a human uses.
    """

    model = ScheduledJob
    form_class = ScheduledJobForm
    fields = [
        "name",
        "description",
        "task_path",
        "kwargs",
        "queue_name",
        "schedule_type",
        "interval_spec",
        "anchor_at",
        "cron_expression",
        "run_at",
        "timezone",
        "enabled",
        "allow_overlap",
        "catch_up",
    ]
    list_fields = ["name", "cadence", "enabled", "last_status", "next_run_at", "total_runs"]
    link_field = "name"
    field_transforms = {
        "cadence": _cadence,
        "last_status": _status_badge,
        "next_run_at": _compact_dt,
    }
    # Give the name + next-run columns room; tighten the flags/counts.
    column_widths = {
        "name": "24%",
        "cadence": "16%",
        "enabled": "9%",
        "last_status": "13%",
        "next_run_at": "18%",
        "total_runs": "10%",
    }
    url_base = "scheduler/jobs"
    paginate_by = 20
    mixins = [StaffRequiredMixin]
    # Jobs are code-owned (@scheduled or programmatic). No hand-creating or
    # deleting from the UI — operators view, override the schedule, and pause.
    actions = [Action.LIST, Action.UPDATE]

    # Custom control page: read-only definition + schedule/enabled overrides.
    form_displays = [ScheduledJobFormDisplay()]

    # Table ⇄ calendar toggle in the display palette. The calendar plots each
    # schedule on its next fire (next_run_at) and tints the chip by the last
    # run's health (see ScheduledJob.calendar_status).
    displays = [
        TableDisplay,
        CalendarDisplay(
            date_field="next_run_at",
            title_field="name",
            status_field="calendar_status",
        ),
    ]

    enable_api = True
    api_extra_fields = ["next_run_at", "last_enqueued_at", "last_status", "total_runs", "source"]

    enable_mcp = True
    mcp_description = "a recurring background schedule (cron/interval/once) that enqueues a task"
    mcp_singular = "schedule"
    mcp_plural = "schedules"

    enable_search = True
    search_fields = ["name", "description", "task_path"]
    search_display = "name"
    search_subtitle = "task_path"


class ScheduledJobRunCRUDView(CRUDView):
    """Read-only run history — a table plus a calendar of runs by outcome.

    Each run is one tick's decision for a schedule (queued/skipped/success/
    failed). The calendar plots runs on their ``scheduled_for`` date and tints
    each chip by outcome (green/amber/red) — the "what actually happened" view
    that complements the jobs page's "what's coming up" calendar.
    """

    model = ScheduledJobRun
    fields = ["job", "status", "scheduled_for", "created_at", "task_result_id", "message"]
    list_fields = ["job", "status", "scheduled_for", "message"]
    link_field = "scheduled_for"
    field_transforms = {"status": _run_status_badge, "scheduled_for": _compact_dt}
    column_widths = {"job": "24%", "status": "13%", "scheduled_for": "20%"}
    url_base = "scheduler/runs"
    paginate_by = 30
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.DETAIL]

    # Table ⇄ calendar toggle. The calendar is the run-history view.
    displays = [
        TableDisplay,
        CalendarDisplay(
            date_field="scheduled_for",
            title_field="job_name",
            status_field="calendar_status",
        ),
    ]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class SchedulerDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "scheduler/dashboard.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        day_ago = now - timedelta(hours=24)

        jobs = ScheduledJob.objects.all()
        runs_24h = ScheduledJobRun.objects.filter(created_at__gte=day_ago)

        ctx["active_jobs"] = jobs.filter(enabled=True).count()
        ctx["total_jobs"] = jobs.count()
        ctx["failures_24h"] = runs_24h.filter(status=ScheduledJobRun.Status.FAILED).count()
        ctx["skipped_24h"] = runs_24h.filter(status=ScheduledJobRun.Status.SKIPPED).count()
        ctx["runs_24h"] = runs_24h.count()

        ctx["upcoming"] = (
            jobs.filter(enabled=True, next_run_at__isnull=False)
            .order_by("next_run_at")[:10]
        )
        nxt = ctx["upcoming"][0].next_run_at if ctx["upcoming"] else None
        ctx["next_run_display"] = f"{nxt:%b %d}" if nxt else "—"
        ctx["next_run_time"] = f"{nxt:%H:%M}" if nxt else ""
        ctx["recent_runs"] = (
            ScheduledJobRun.objects.select_related("job").order_by("-created_at")[:15]
        )
        ctx["timeline"] = _run_timeline(hours=24)
        return ctx


def _run_timeline(*, hours: int) -> list[dict]:
    """Hourly buckets of run outcomes for the dashboard bar strip.

    One aggregate query, constant regardless of job count (guards against the
    N-jobs query blowup the runbook/heartbeat regression tests watch for).
    """
    now = timezone.now()
    start = now - timedelta(hours=hours)
    buckets = {}
    rows = (
        ScheduledJobRun.objects.filter(created_at__gte=start)
        .values_list("created_at", "status")
    )
    for created, status in rows:
        key = created.replace(minute=0, second=0, microsecond=0)
        b = buckets.setdefault(key, {"success": 0, "failed": 0, "skipped": 0, "queued": 0})
        b[status] = b.get(status, 0) + 1

    out = []
    for i in range(hours, -1, -1):
        hour = (now - timedelta(hours=i)).replace(minute=0, second=0, microsecond=0)
        counts = buckets.get(hour, {"success": 0, "failed": 0, "skipped": 0, "queued": 0})
        total = sum(counts.values())
        out.append({"hour": hour, "total": total, **counts})
    return out


# ---------------------------------------------------------------------------
# Stat-card drill-downs
# ---------------------------------------------------------------------------


def scheduler_stat_detail(request: HttpRequest, stat_type: str) -> HttpResponse:
    """hx-get body for the dashboard stat cards."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    now = timezone.now()

    if stat_type == "active":
        qs = ScheduledJob.objects.filter(enabled=True).order_by("next_run_at")
        rows = [
            stat_list_row(
                j.name,
                href=reverse("scheduler/jobs-update", args=[j.pk]),
                meta=j.cadence_display,
                count=j.total_runs,
            )
            for j in qs
        ]
        return render_stat_list(rows, empty="No active schedules.")

    if stat_type in {"failed", "skipped"}:
        status = ScheduledJobRun.Status.FAILED if stat_type == "failed" else ScheduledJobRun.Status.SKIPPED
        qs = (
            ScheduledJobRun.objects.select_related("job")
            .filter(status=status, created_at__gte=now - timedelta(hours=24))
            .order_by("-created_at")
        )
        rows = [
            stat_list_row(
                r.job.name,
                href=reverse("scheduler/jobs-update", args=[r.job_id]),
                meta=r.message or f"{r.created_at:%H:%M}",
            )
            for r in qs
        ]
        return render_stat_list(rows, empty=f"No {stat_type} runs in the last 24h.")

    if stat_type == "upcoming":
        qs = ScheduledJob.objects.filter(enabled=True, next_run_at__isnull=False).order_by("next_run_at")[:25]
        rows = [
            stat_list_row(
                j.name,
                href=reverse("scheduler/jobs-update", args=[j.pk]),
                meta=f"{j.next_run_at:%Y-%m-%d %H:%M}",
            )
            for j in qs
        ]
        return render_stat_list(rows, empty="Nothing scheduled.")

    return HttpResponse(status=404)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@require_POST
def run_now(request: HttpRequest, pk: int) -> HttpResponse:
    """Enqueue a job immediately, off-schedule (staff-only)."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    job = get_object_or_404(ScheduledJob, pk=pk)
    try:
        services.enqueue_and_record(job, scheduled_for=timezone.now())
        messages.success(request, f"“{job.name}” enqueued.")
    except Exception as exc:  # noqa: BLE001 — surface the failure to the operator
        messages.error(request, f"Could not enqueue “{job.name}”: {exc}")
    return redirect("scheduler_dashboard")


@require_POST
def reset_schedule(request: HttpRequest, pk: int) -> HttpResponse:
    """Clear a UI schedule override so the job snaps back to its code cadence."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return HttpResponse(status=403)
    job = get_object_or_404(ScheduledJob, pk=pk)
    if job.schedule_overridden:
        job.schedule_overridden = False
        job.save(update_fields=["schedule_overridden"])
        try:
            from .registry import sync_code_jobs

            sync_code_jobs()  # re-applies the @scheduled cadence when a spec exists
        except Exception:  # noqa: BLE001 — never let re-sync block the reset
            pass
        messages.success(request, f"“{job.name}” schedule reset to the code default.")
    return redirect("scheduler/jobs-update", pk=pk)


@csrf_exempt
@require_POST
def scheduler_tick(request: HttpRequest) -> JsonResponse:
    """Localhost-only endpoint for cron to drive the tick inside gunicorn.

    Mirrors heartbeat_ping: running the tick in a web worker avoids the SQLite
    lock contention a separate manage.py process would cause. Use exactly one
    trigger per deployment.
    """
    if request.META.get("REMOTE_ADDR", "") not in LOCALHOST_IPS:
        return JsonResponse({"error": "forbidden"}, status=403)
    result = services.run_due_jobs()
    services.reconcile_run_outcomes()
    return JsonResponse(
        {
            "enqueued": result.enqueued,
            "skipped": result.skipped,
            "retired": result.retired,
            "errors": result.errors,
        }
    )
