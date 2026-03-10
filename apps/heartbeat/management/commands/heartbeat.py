"""Management command to run a heartbeat check."""

import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Avg, Count, Q
from django.utils.timezone import now

from apps.heartbeat.models import Heartbeat, HeartbeatDaily, HeartbeatEpoch


class Command(BaseCommand):
    help = "Run a heartbeat check (DB connectivity) and record the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-epoch",
            action="store_true",
            help="Reset the monitoring epoch to now (restarts uptime tracking).",
        )
        parser.add_argument(
            "--reset-note",
            type=str,
            default="",
            help="Optional note for the epoch reset (e.g. 'After server migration').",
        )

    def handle(self, **options):
        if options["reset_epoch"]:
            note = options["reset_note"]
            epoch = HeartbeatEpoch.reset(note=note)
            self.stdout.write(f"Epoch reset to {epoch.started_at:%Y-%m-%d %H:%M:%S}")
            if note:
                self.stdout.write(f"  Note: {note}")
            return

        minute = now().replace(second=0, microsecond=0)
        start = time.monotonic()
        try:
            connection.ensure_connection()
            elapsed = int((time.monotonic() - start) * 1000)
            # update_or_create: if a beat already exists for this minute
            # (loop drift), update it instead of creating a duplicate.
            _, created = Heartbeat.objects.update_or_create(
                timestamp=minute,
                defaults={"status": "ok", "response_time_ms": elapsed},
            )
            self.stdout.write(f"Heartbeat OK ({elapsed}ms){'' if created else ' (updated)'}")
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            Heartbeat.objects.update_or_create(
                timestamp=minute,
                defaults={
                    "status": "fail",
                    "response_time_ms": elapsed,
                    "note": str(e)[:255],
                },
            )
            self.stderr.write(f"Heartbeat FAIL: {e}")

        # Auto-create epoch on first heartbeat
        HeartbeatEpoch.ensure_epoch()

        # Prune old records, writing daily summaries first
        retention_days = getattr(settings, "HEARTBEAT_RETENTION_DAYS", 7)
        interval = getattr(settings, "HEARTBEAT_EXPECTED_INTERVAL", 60)
        cutoff = now() - timedelta(days=retention_days)
        old_records = Heartbeat.objects.filter(timestamp__lt=cutoff)

        if old_records.exists():
            self._write_daily_summaries(old_records, interval)
            deleted, _ = old_records.delete()
            self.stdout.write(f"Pruned {deleted} old heartbeat records")

    def _write_daily_summaries(self, queryset, interval):
        """Aggregate about-to-be-pruned records into daily summaries."""
        daily_stats = (
            queryset.values("timestamp__date")
            .annotate(
                ok_count=Count("pk", filter=Q(status="ok")),
                fail_count=Count("pk", filter=Q(status="fail")),
                total=Count("pk"),
                avg_ms=Avg("response_time_ms"),
            )
            .order_by("timestamp__date")
        )

        expected_per_day = (24 * 3600) // interval

        for day in daily_stats:
            date = day["timestamp__date"]
            ok = day["ok_count"]
            fail = day["fail_count"]
            total = day["total"]
            avg_ms = int(day["avg_ms"] or 0)

            # Use the larger of actual total or expected as denominator
            denominator = max(total, expected_per_day)
            uptime = round((ok / denominator) * 100, 3) if denominator > 0 else 0

            HeartbeatDaily.objects.update_or_create(
                date=date,
                defaults={
                    "ok_count": ok,
                    "fail_count": fail,
                    "expected_count": expected_per_day,
                    "avg_response_ms": avg_ms,
                    "uptime_pct": uptime,
                },
            )
