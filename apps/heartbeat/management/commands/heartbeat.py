"""Management command to run a heartbeat check."""

from django.core.management.base import BaseCommand

from apps.heartbeat.models import HeartbeatEpoch
from apps.heartbeat.services import prune_old_heartbeats, run_all_monitors


class Command(BaseCommand):
    help = "Run all registered monitor checks and record their results."

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
        parser.add_argument(
            "--repair-summaries",
            action="store_true",
            help=(
                "Delete daily-summary rows corrupted by the pre-v0.21.3 "
                "batch-overwrite prune bug (a summarized day kept only its "
                "final beat, rendering as ~0.07%% 'down'). The real counts are "
                "unrecoverable, so affected days become 'No data' on the "
                "status page. Run once after upgrading."
            ),
        )

    def handle(self, **options):
        if options["repair_summaries"]:
            self._repair_summaries()
            return
        if options["reset_epoch"]:
            note = options["reset_note"]
            epoch = HeartbeatEpoch.reset(note=note)
            self.stdout.write(f"Epoch reset to {epoch.started_at:%Y-%m-%d %H:%M:%S}")
            if note:
                self.stdout.write(f"  Note: {note}")
            return

        results = run_all_monitors()

        for key, result in results.items():
            if result["status"] == "ok":
                suffix = "" if result.get("created") else " (updated)"
                maint_tag = " [maintenance]" if result.get("maintenance") else ""
                self.stdout.write(f"{key}: OK ({result['response_time_ms']}ms){suffix}{maint_tag}")
            else:
                self.stderr.write(f"{key}: FAIL — {result.get('note')}")

        deleted = prune_old_heartbeats()
        if deleted:
            self.stdout.write(f"Pruned {deleted} old heartbeat records")

    def _repair_summaries(self) -> None:
        """Delete summaries whose recorded beats are an implausibly small
        fraction of the expected count — the fingerprint of the overwrite bug.

        A genuine recorded outage keeps its ~full-day fail beats; a day the
        host was off has no row at all. Only the corrupted rows (typically a
        single surviving beat of 1440 expected) sit far below the threshold.
        """
        from django.db.models import ExpressionWrapper, F, FloatField

        from apps.heartbeat.models import HeartbeatDaily

        corrupt = (
            HeartbeatDaily.objects.filter(expected_count__gt=0)
            .annotate(
                recorded_frac=ExpressionWrapper(
                    (F("ok_count") + F("fail_count")) * 1.0 / F("expected_count"),
                    output_field=FloatField(),
                )
            )
            .filter(recorded_frac__lt=0.05)
        )
        by_monitor: dict[str, int] = {}
        for row in corrupt:
            by_monitor[row.monitor_key] = by_monitor.get(row.monitor_key, 0) + 1
        count = corrupt.count()
        if not count:
            self.stdout.write("No corrupted daily summaries found.")
            return
        corrupt.delete()
        self.stdout.write(f"Deleted {count} corrupted daily summaries (now 'No data'):")
        for key, n in sorted(by_monitor.items()):
            self.stdout.write(f"  {key}: {n} day(s)")
