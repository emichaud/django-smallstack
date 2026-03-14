"""Models for heartbeat/uptime monitoring."""

from django.db import models
from django.utils.timezone import now


class HeartbeatEpoch(models.Model):
    """Tracks the monitoring start time and SLA targets.

    Single-row table. The epoch is the baseline for "since when are we
    counting uptime?" — defaults to the first heartbeat, resettable via
    the SLA page or management command.
    """

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
        verbose_name = "Heartbeat Epoch"
        verbose_name_plural = "Heartbeat Epoch"

    def __str__(self):
        return f"Monitoring since {self.started_at:%Y-%m-%d %H:%M}"

    @classmethod
    def get_epoch(cls):
        """Return the current epoch timestamp, or None if no monitoring has started."""
        obj = cls.objects.first()
        if obj:
            return obj.started_at
        oldest = Heartbeat.objects.order_by("timestamp").values_list("timestamp", flat=True).first()
        return oldest

    @classmethod
    def get_config(cls):
        """Return the epoch config object, or None."""
        return cls.objects.first()

    @classmethod
    def get_sla_targets(cls):
        """Return (service_target, service_minimum) as floats."""
        obj = cls.objects.first()
        if obj:
            return float(obj.service_target), float(obj.service_minimum)
        return 99.9, 99.5

    @classmethod
    def reset(cls, note="", started_at=None, service_target=None, service_minimum=None):
        """Reset the epoch. Returns the new epoch object.

        started_at is truncated to the minute to align with heartbeat timestamps.
        """
        old = cls.objects.first()
        ts = started_at or now()
        ts = ts.replace(second=0, microsecond=0)
        defaults = {
            "started_at": ts,
            "note": note,
            "service_target": service_target if service_target is not None else (old.service_target if old else 99.9),
            "service_minimum": (
                service_minimum if service_minimum is not None else (old.service_minimum if old else 99.5)
            ),
        }
        cls.objects.all().delete()
        return cls.objects.create(**defaults)

    @classmethod
    def ensure_epoch(cls):
        """Create the epoch from the first heartbeat if it doesn't exist yet."""
        if cls.objects.exists():
            return cls.objects.first()
        oldest = Heartbeat.objects.order_by("timestamp").values_list("timestamp", flat=True).first()
        if oldest:
            return cls.objects.create(started_at=oldest, note="Auto-created from first heartbeat")
        return None


class HeartbeatDaily(models.Model):
    """Daily summary of heartbeat data for long-term SLA tracking.

    One row per day, written during heartbeat pruning. Survives after
    individual heartbeat records are pruned.
    """

    date = models.DateField(unique=True, db_index=True)
    ok_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    expected_count = models.PositiveIntegerField(default=0)
    avg_response_ms = models.PositiveIntegerField(default=0)
    uptime_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Daily Summary"
        verbose_name_plural = "Daily Summaries"

    def __str__(self):
        return f"{self.date} — {self.uptime_pct}% ({self.ok_count}/{self.expected_count})"

    @classmethod
    def get_daily_summary(cls, days=7):
        """Return a list of daily ok/fail dicts for the last N days.

        Always returns exactly `days` entries (oldest first), filling in
        zeros for any day without a record.
        """
        import datetime

        from django.utils import timezone

        today = timezone.localdate()
        lookup = {d.date: d for d in cls.objects.filter(
            date__gte=today - datetime.timedelta(days=days - 1),
        )}
        result = []
        for i in range(days - 1, -1, -1):
            day = today - datetime.timedelta(days=i)
            d = lookup.get(day)
            result.append({
                "label": day.strftime("%a"),
                "date": day.isoformat(),
                "ok": d.ok_count if d else 0,
                "fail": d.fail_count if d else 0,
            })
        return result


class Heartbeat(models.Model):
    """Records a single heartbeat check result."""

    timestamp = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=10,
        choices=[("ok", "OK"), ("fail", "Fail")],
    )
    response_time_ms = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True, default="")

    def save(self, *args, **kwargs):
        if not self.timestamp:
            self.timestamp = now().replace(second=0, microsecond=0)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-timestamp"]
        get_latest_by = "timestamp"

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} [{self.status}] {self.response_time_ms}ms"
