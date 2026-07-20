"""Scheduler models — ScheduledJob (the schedule) + ScheduledJobRun (history).

The scheduler owns *timing, overlap, and history*. The django.tasks engine owns
*execution and results*. A ``ScheduledJobRun`` links to the engine's
``DBTaskResult`` by id (``task_result_id``) rather than duplicating status /
return value / traceback — those are read back from the task engine.
"""

from __future__ import annotations

from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from . import schedules


class ScheduledJob(models.Model):
    """A recurring (or one-off) schedule that enqueues a django.tasks task."""

    class Type(models.TextChoices):
        ONCE = "once", "Once"
        INTERVAL = "interval", "Interval"
        CRON = "cron", "Cron"

    class Kind(models.TextChoices):
        TASK = "task", "Task"
        # Reserved seams — not executed in v1 (see scheduler-spec §11).
        COMMAND = "command", "Management command"
        AGENT = "agent", "AI agent"

    class Source(models.TextChoices):
        CODE = "code", "Code (@scheduled)"
        UI = "ui", "UI"

    class CatchUp(models.TextChoices):
        RUN_ONCE = "run_once", "Run once, then resume"
        SKIP = "skip", "Skip missed runs"

    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    job_kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TASK)
    # Dotted path to a registered @task (v1) — e.g. "apps.tasks.tasks.send_email_task".
    task_path = models.CharField(max_length=300)
    kwargs = models.JSONField(default=dict, blank=True)
    queue_name = models.CharField(max_length=64, default="default")

    schedule_type = models.CharField(max_length=10, choices=Type.choices)
    # interval: e.g. "5m", "2h", "1d", "90d", "1mo", "1y"
    interval_spec = models.CharField(max_length=20, blank=True)
    # Optional phase anchor for interval schedules ("every 90d from X").
    anchor_at = models.DateTimeField(null=True, blank=True)
    # cron: standard 5-field expression, evaluated in `timezone`.
    cron_expression = models.CharField(max_length=100, blank=True)
    # once:
    run_at = models.DateTimeField(null=True, blank=True)
    # Evaluation timezone name (e.g. "America/New_York"); blank → project TZ.
    timezone = models.CharField(max_length=64, blank=True)

    enabled = models.BooleanField(default=True)
    allow_overlap = models.BooleanField(
        default=False,
        help_text="If off, skip a fire while the previous run is still unfinished.",
    )
    catch_up = models.CharField(max_length=10, choices=CatchUp.choices, default=CatchUp.RUN_ONCE)
    max_retries = models.PositiveSmallIntegerField(default=0, help_text="Reserved (Phase 3).")

    source = models.CharField(max_length=8, choices=Source.choices, default=Source.UI)
    # An operator changed the cadence in the UI. Code sync keeps their value
    # instead of reverting to the @scheduled default (task/kwargs still sync).
    schedule_overridden = models.BooleanField(default=False)

    # Bookkeeping maintained by the tick.
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=20, blank=True)
    total_runs = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Scheduled Job"
        verbose_name_plural = "Scheduled Jobs"

    def __str__(self) -> str:
        return self.name

    # -- validation -------------------------------------------------------

    def clean(self) -> None:
        """Reject incoherent cadences at save time, not at 2am in the tick."""
        required = {
            self.Type.ONCE: ("run_at", self.run_at),
            self.Type.INTERVAL: ("interval_spec", self.interval_spec),
            self.Type.CRON: ("cron_expression", self.cron_expression),
        }.get(self.schedule_type)
        if required is None:
            raise ValidationError({"schedule_type": "Choose once, interval, or cron."})
        field_name, value = required
        if not value:
            raise ValidationError({field_name: f"Required for a {self.schedule_type} schedule."})
        # Surfaces bad interval/cron/timezone strings as a clean field error.
        try:
            schedules.next_run(self, after=timezone.now())
        except schedules.ScheduleConfigError as exc:
            raise ValidationError({field_name: str(exc)}) from exc

    # Fields that define *when* the job fires. A change to any of them must
    # re-seed next_run_at (see save()), so a retune actually takes effect.
    CADENCE_FIELDS = (
        "schedule_type",
        "interval_spec",
        "cron_expression",
        "run_at",
        "timezone",
        "anchor_at",
    )

    def save(self, *args: object, **kwargs: object) -> None:
        # Re-seed next_run_at when the schedule is freshly enabled (cursor is
        # None) OR its cadence changed — so a retune via the themed form, the
        # REST/MCP update path, or a programmatic edit takes effect on the *next*
        # tick instead of firing once more on the stale cadence.
        # A malformed cadence saved without full_clean() (e.g. a direct .create())
        # leaves the row unscheduled rather than raising out of save() — clean()
        # is the real gate; this just avoids a 500 on the unvalidated path.
        cadence_changed = self._cadence_changed()
        if self.enabled and (self.next_run_at is None or cadence_changed):
            try:
                self.next_run_at = self.compute_next_run(after=timezone.now())
            except schedules.ScheduleConfigError:
                self.next_run_at = None
            # Make the recompute stick even under a partial update_fields save
            # (e.g. a serializer that saves only the changed fields).
            uf = kwargs.get("update_fields")
            if uf is not None and "next_run_at" not in uf:
                kwargs["update_fields"] = [*uf, "next_run_at"]
        super().save(*args, **kwargs)

    def _cadence_changed(self) -> bool:
        """True if this is an update whose cadence differs from the stored row."""
        if not self.pk:
            return False
        old = type(self).objects.filter(pk=self.pk).values(*self.CADENCE_FIELDS).first()
        if old is None:
            return False
        return any(old[f] != getattr(self, f) for f in self.CADENCE_FIELDS)

    # -- helpers ----------------------------------------------------------

    def compute_next_run(self, *, after: datetime) -> datetime | None:
        return schedules.next_run(self, after=after)

    @property
    def cadence_display(self) -> str:
        if self.schedule_type == self.Type.ONCE:
            return f"once @ {self.run_at:%Y-%m-%d %H:%M}" if self.run_at else "once"
        if self.schedule_type == self.Type.INTERVAL:
            anchored = f" from {self.anchor_at:%Y-%m-%d}" if self.anchor_at else ""
            return f"every {self.interval_spec}{anchored}"
        return f"cron: {self.cron_expression}"

    @property
    def calendar_status(self) -> str:
        """Map last-run status → CalendarDisplay chip tint (success/warning/danger).

        The jobs calendar plots each schedule on its next fire; tinting that chip
        by the previous run's outcome gives an at-a-glance health signal.
        """
        return {
            "success": "success",
            "failed": "danger",
            "invalid": "danger",
            "skipped": "warning",
        }.get(self.last_status, "")


class ScheduledJobRun(models.Model):
    """Append-only record of one tick's decision for a job.

    Status is the *scheduler-side* view (did we enqueue / skip). Execution
    outcome (success/failure/traceback/duration) lives on the linked
    ``DBTaskResult`` and is joined via ``task_result_id``.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SKIPPED = "skipped", "Skipped"
        # Mirrors of engine terminal states, summarized onto the run for the
        # dashboard/timeline without a join at read time.
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    job = models.ForeignKey(ScheduledJob, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=10, choices=Status.choices)
    scheduled_for = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    # UUID of the engine's DBTaskResult (blank for skipped runs).
    task_result_id = models.CharField(max_length=64, blank=True, db_index=True)
    message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Scheduled Job Run"
        verbose_name_plural = "Scheduled Job Runs"
        indexes = [models.Index(fields=["job", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.job_id} · {self.status} @ {self.scheduled_for:%Y-%m-%d %H:%M}"

    @property
    def job_name(self) -> str:
        """The parent schedule's name — the run-history calendar chip label."""
        return self.job.name

    @property
    def calendar_status(self) -> str:
        """Map run status → CalendarDisplay chip tint (success/warning/danger)."""
        return {
            "success": "success",
            "failed": "danger",
            "skipped": "warning",
        }.get(self.status, "")
