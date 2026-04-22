"""Management command to run a heartbeat check."""

from django.core.management.base import BaseCommand

from apps.heartbeat.models import HeartbeatEpoch
from apps.heartbeat.services import prune_old_heartbeats, run_heartbeat_check


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

        result = run_heartbeat_check()

        if result["status"] == "ok":
            suffix = "" if result["created"] else " (updated)"
            maint_tag = " [maintenance]" if result["maintenance"] else ""
            self.stdout.write(f"Heartbeat OK ({result['response_time_ms']}ms){suffix}{maint_tag}")
        else:
            self.stderr.write(f"Heartbeat FAIL: {result['note']}")

        deleted = prune_old_heartbeats()
        if deleted:
            self.stdout.write(f"Pruned {deleted} old heartbeat records")
