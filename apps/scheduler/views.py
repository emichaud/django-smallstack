"""Scheduler views — CRUDView, dashboard, the tick endpoint, and run-now."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.mixins import StaffRequiredMixin
from apps.smallstack.stat_lists import render_stat_list, stat_list_row

from . import services
from .forms import ScheduledJobForm
from .models import ScheduledJob, ScheduledJobRun

LOCALHOST_IPS = {"127.0.0.1", "::1"}


def _status_badge(value, obj):
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


def _cadence(value, obj):
    return obj.cadence_display


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
    field_transforms = {"cadence": _cadence, "last_status": _status_badge}
    url_base = "scheduler/jobs"
    paginate_by = 20
    mixins = [StaffRequiredMixin]
    actions = [Action.LIST, Action.CREATE, Action.UPDATE, Action.DELETE]

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
        task_result_id = services._enqueue(job)
        services._record(job, ScheduledJobRun.Status.QUEUED, timezone.now(), task_result_id=task_result_id)
        ScheduledJob.objects.filter(pk=job.pk).update(
            last_enqueued_at=timezone.now(),
            last_status=ScheduledJobRun.Status.QUEUED,
            total_runs=job.total_runs + 1,
        )
        messages.success(request, f"“{job.name}” enqueued.")
    except Exception as exc:  # noqa: BLE001 — surface the failure to the operator
        messages.error(request, f"Could not enqueue “{job.name}”: {exc}")
    return redirect("scheduler_dashboard")


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
