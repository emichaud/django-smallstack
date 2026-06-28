"""Models for heartbeat/uptime monitoring."""

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.db import models, transaction
from django.utils.timezone import now


class HeartbeatEpoch(models.Model):
    """Tracks the monitoring start time and SLA targets.

    Single-row table. The epoch is the baseline for "since when are we
    counting uptime?" — defaults to the first heartbeat, resettable via
    the SLA page or management command.
    """

    # Which monitor this epoch belongs to. One epoch row per monitor; "site" is
    # the built-in database/uptime monitor (back-filled onto pre-existing rows).
    monitor_key = models.SlugField(default="site", db_index=True)
    started_at = models.DateTimeField()
    note = models.CharField(max_length=255, blank=True, default="")
    service_target = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=99.9,
        help_text="SLA target uptime % (goal for internal tracking)",
    )
    service_minimum = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=99.5,
        help_text="SLA minimum uptime % (threshold for public status)",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Heartbeat Epoch"
        verbose_name_plural = "Heartbeat Epochs"
        constraints = [models.UniqueConstraint(fields=["monitor_key"], name="unique_epoch_per_monitor")]

    def __str__(self) -> str:
        return f"[{self.monitor_key}] monitoring since {self.started_at:%Y-%m-%d %H:%M}"

    @classmethod
    def get_epoch(cls, monitor_key: str = "site") -> datetime | None:
        """Return the monitor's epoch timestamp, or None if monitoring hasn't started."""
        obj = cls.objects.filter(monitor_key=monitor_key).first()
        if obj:
            return obj.started_at
        return (
            Heartbeat.objects.filter(monitor_key=monitor_key)
            .order_by("timestamp")
            .values_list("timestamp", flat=True)
            .first()
        )

    @classmethod
    def get_config(cls, monitor_key: str = "site") -> "HeartbeatEpoch | None":
        """Return the monitor's epoch config object, or None."""
        return cls.objects.filter(monitor_key=monitor_key).first()

    @classmethod
    def get_sla_targets(cls, monitor_key: str = "site") -> tuple[float, float]:
        """Return (service_target, service_minimum) as floats for the monitor."""
        obj = cls.objects.filter(monitor_key=monitor_key).first()
        if obj:
            return float(obj.service_target), float(obj.service_minimum)
        return 99.9, 99.5

    @classmethod
    def reset(
        cls,
        note="",
        started_at=None,
        service_target=None,
        service_minimum=None,
        monitor_key: str = "site",
    ) -> "HeartbeatEpoch":
        """Reset the monitor's epoch. Returns the new epoch object.

        started_at is truncated to the minute to align with heartbeat timestamps.
        Only this monitor's epoch is replaced — other monitors are untouched.
        """
        old = cls.objects.filter(monitor_key=monitor_key).first()
        ts = started_at or now()
        ts = ts.replace(second=0, microsecond=0)
        defaults = {
            "monitor_key": monitor_key,
            "started_at": ts,
            "note": note,
            "service_target": service_target if service_target is not None else (old.service_target if old else 99.9),
            "service_minimum": (
                service_minimum if service_minimum is not None else (old.service_minimum if old else 99.5)
            ),
        }
        # Atomic so a failure between delete and create can't leave this monitor
        # without an epoch and silently restart its SLA tracking. (Audit L10.)
        with transaction.atomic():
            cls.objects.filter(monitor_key=monitor_key).delete()
            return cls.objects.create(**defaults)

    @classmethod
    def ensure_epoch(cls, monitor_key: str = "site") -> "HeartbeatEpoch | None":
        """Create the monitor's epoch from its first heartbeat if missing."""
        existing = cls.objects.filter(monitor_key=monitor_key).first()
        if existing:
            return existing
        oldest = (
            Heartbeat.objects.filter(monitor_key=monitor_key)
            .order_by("timestamp")
            .values_list("timestamp", flat=True)
            .first()
        )
        if oldest:
            return cls.objects.create(
                monitor_key=monitor_key, started_at=oldest, note="Auto-created from first heartbeat"
            )
        return None


class MaintenanceWindow(models.Model):
    """A scheduled maintenance window for excluding downtime from SLA calculations."""

    # The monitor these windows apply to ("site" = the built-in uptime monitor).
    monitor_key = models.SlugField(default="site", db_index=True)
    title = models.CharField(max_length=200)
    start = models.DateTimeField()
    end = models.DateTimeField()
    note = models.TextField(blank=True, default="")
    exclude_from_sla = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start"]

    def __str__(self) -> str:
        return f"{self.title} ({self.start:%Y-%m-%d %H:%M} – {self.end:%H:%M})"

    @classmethod
    def is_in_maintenance(cls, dt, monitor_key: str = "site") -> bool:
        """Check if a datetime falls within any of the monitor's maintenance windows."""
        return cls.objects.filter(monitor_key=monitor_key, start__lte=dt, end__gt=dt).exists()

    @classmethod
    def get_excluded_ranges(cls, range_start, range_end, monitor_key: str = "site") -> list[tuple[datetime, datetime]]:
        """Return merged (start, end) tuples of the monitor's SLA-excluded windows overlapping the range."""
        windows = (
            cls.objects.filter(
                monitor_key=monitor_key,
                exclude_from_sla=True,
                start__lt=range_end,
                end__gt=range_start,
            )
            .order_by("start")
            .values_list("start", "end")
        )

        merged = []
        for ws, we in windows:
            s = max(ws, range_start)
            e = min(we, range_end)
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged

    @classmethod
    def get_excluded_seconds(cls, range_start, range_end, monitor_key: str = "site") -> float:
        """Total seconds excluded from SLA in the given range (merged to avoid double-counting)."""
        return sum((e - s).total_seconds() for s, e in cls.get_excluded_ranges(range_start, range_end, monitor_key))


class HeartbeatDaily(models.Model):
    """Daily summary of heartbeat data for long-term SLA tracking.

    One row per day, written during heartbeat pruning. Survives after
    individual heartbeat records are pruned.
    """

    monitor_key = models.SlugField(default="site", db_index=True)
    date = models.DateField(db_index=True)
    ok_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    maintenance_count = models.PositiveIntegerField(default=0)
    expected_count = models.PositiveIntegerField(default=0)
    avg_response_ms = models.PositiveIntegerField(default=0)
    uptime_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Daily Summary"
        verbose_name_plural = "Daily Summaries"
        constraints = [models.UniqueConstraint(fields=["monitor_key", "date"], name="unique_daily_per_monitor")]

    def __str__(self) -> str:
        return f"[{self.monitor_key}] {self.date} — {self.uptime_pct}% ({self.ok_count}/{self.expected_count})"

    @property
    def sla_status(self) -> str | None:
        """Classify this day's uptime against SLA targets.

        Returns ``"success"`` when uptime meets the target, ``"warning"`` when
        it meets the minimum (but not the target), ``"danger"`` when below
        minimum, or ``None`` when there's no meaningful sample.
        """
        if (self.ok_count + self.fail_count) == 0:
            return None
        target, minimum = HeartbeatEpoch.get_sla_targets(self.monitor_key)
        uptime = float(self.uptime_pct)
        if uptime >= float(target):
            return "success"
        if uptime >= float(minimum):
            return "warning"
        return "danger"

    @classmethod
    def get_daily_summary(cls, days: int = 7, monitor_key: str = "site") -> list[dict[str, Any]]:
        """Return a list of daily ok/fail dicts for the last N days.

        Always returns exactly `days` entries (oldest first), filling in
        zeros for any day without a record.
        """
        import datetime

        from django.utils import timezone

        today = timezone.localdate()
        lookup = {
            d.date: d
            for d in cls.objects.filter(
                monitor_key=monitor_key,
                date__gte=today - datetime.timedelta(days=days - 1),
            )
        }
        result = []
        for i in range(days - 1, -1, -1):
            day = today - datetime.timedelta(days=i)
            d = lookup.get(day)
            result.append(
                {
                    "label": day.strftime("%a"),
                    "date": day.isoformat(),
                    "ok": d.ok_count if d else 0,
                    "fail": d.fail_count if d else 0,
                }
            )
        return result


class MonitoredEndpoint(models.Model):
    """A user-created HTTP endpoint to monitor, tagged to a service.

    Each enabled row becomes a live monitor via the ``register_monitor_source``
    seam (see ``apps/heartbeat/monitors.py``). Its heartbeats are stored under
    ``monitor_key = "ep_<slug>"`` so they never collide with built-in monitors.
    """

    HTTP_METHODS = [("GET", "GET"), ("HEAD", "HEAD"), ("POST", "POST")]

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="Stable identifier; forms the monitor key.")
    service = models.SlugField(
        default="custom",
        help_text="Which service this monitor relates to: site, api, mcp, search, or custom.",
    )
    url = models.URLField(max_length=500)
    method = models.CharField(max_length=8, choices=HTTP_METHODS, default="GET")
    expected_status = models.PositiveIntegerField(default=200, help_text="HTTP status that counts as up.")
    timeout_seconds = models.PositiveSmallIntegerField(default=10)
    enabled = models.BooleanField(default=True)
    public = models.BooleanField(
        default=False, help_text="Mark this monitor as public (intended for the public status board)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Monitored Endpoint"
        verbose_name_plural = "Monitored Endpoints"

    def __str__(self) -> str:
        return f"{self.name} ({self.url})"

    @property
    def monitor_key(self) -> str:
        """The Heartbeat.monitor_key for this endpoint (slug-safe, collision-proof)."""
        return f"ep_{self.slug}"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        from apps.smallstack.monitors import get_services

        errors: dict[str, str] = {}
        if urlparse(self.url).scheme.lower() not in ("http", "https"):
            errors["url"] = "URL must start with http:// or https://."
        # A monitor tagged to an unregistered service would never appear on the
        # overview (grouped by registered services) yet still run every minute.
        valid = {s.key for s in get_services()}
        if valid and self.service not in valid:
            errors["service"] = f"Unknown service. Choose one of: {', '.join(sorted(valid))}."
        if errors:
            raise ValidationError(errors)


class MonitoredSurface(models.Model):
    """A user-picked *internal* surface to monitor (the "Site Monitors" tier).

    Unlike :class:`MonitoredEndpoint` (an arbitrary external URL), a surface is one
    of the things SmallStack itself exposes — a REST resource (``enable_api``) or an
    MCP tool — chosen from the live registry of what's currently exposed (see
    :mod:`apps.heartbeat.surfaces`). Each enabled row becomes a live monitor via the
    ``register_monitor_source`` seam, stored under ``monitor_key = "sm_<slug>"``.

    The ``(kind, target)`` pair identifies the surface: it's matched against the
    exposed set to detect *orphans* (the surface was removed or its ``enable_api`` /
    MCP registration turned off) and to find an app-published override check
    (:func:`apps.smallstack.monitors.register_surface_check`).
    """

    KIND_CHOICES = [("api", "API endpoint"), ("mcp", "MCP tool")]

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    target = models.CharField(
        max_length=200,
        help_text="The exposed surface's identifier (REST registry name or MCP tool name).",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True, help_text="Stable identifier; forms the monitor key.")
    enabled = models.BooleanField(default=True)
    public = models.BooleanField(
        default=False, help_text="Mark this monitor as public (intended for the public status board)."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Site Monitor"
        verbose_name_plural = "Site Monitors"
        constraints = [models.UniqueConstraint(fields=["kind", "target"], name="unique_surface_per_target")]

    def __str__(self) -> str:
        return f"{self.name} ({self.kind}:{self.target})"

    @property
    def monitor_key(self) -> str:
        """The Heartbeat.monitor_key for this surface (slug-safe, collision-proof)."""
        return f"sm_{self.slug}"

    @property
    def is_exposed(self) -> bool:
        """Whether the picked surface is still exposed (False ⇒ orphaned)."""
        from .surfaces import is_surface_exposed

        return is_surface_exposed(self.kind, self.target)


class Heartbeat(models.Model):
    """Records a single heartbeat check result for one monitor."""

    # Which monitor produced this beat ("site" = the built-in uptime monitor).
    monitor_key = models.SlugField(default="site", db_index=True)
    timestamp = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=10,
        choices=[("ok", "OK"), ("fail", "Fail")],
    )
    response_time_ms = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True, default="")
    maintenance = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.timestamp:
            self.timestamp = now().replace(second=0, microsecond=0)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-timestamp"]
        get_latest_by = "timestamp"
        # Unique per monitor per minute — guards update_or_create against
        # duplicate rows under concurrent runs (cron + the localhost ping), and
        # serves as the (monitor_key, timestamp) lookup index.
        constraints = [
            models.UniqueConstraint(fields=["monitor_key", "timestamp"], name="unique_beat_per_monitor_minute"),
        ]

    def __str__(self) -> str:
        return f"[{self.monitor_key}] {self.timestamp:%Y-%m-%d %H:%M} [{self.status}] {self.response_time_ms}ms"
