"""Self-contained beat loop for dev / single-process deployments.

Wakes every ``--interval`` seconds and runs one tick. In production prefer the
cron POST (runs inside gunicorn, no SQLite lock contention); this loop is handy
for ``make run`` and can be supervised inline like ``db_worker`` in
``docker-entrypoint.sh``.
"""

from __future__ import annotations

import signal
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.scheduler.services import reconcile_run_outcomes, run_due_jobs


class Command(BaseCommand):
    help = "Run the scheduler as a foreground loop (dev/single-process)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--interval", type=int, default=60, help="Seconds between ticks.")
        parser.add_argument("--once", action="store_true", help="Run one tick and exit.")

    def handle(self, *args: Any, **options: Any) -> None:
        interval = max(1, options["interval"])
        self._running = True

        def _stop(*_a: object) -> None:
            self._running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        self.stdout.write(self.style.SUCCESS(f"scheduler_beat: tick every {interval}s (Ctrl-C to stop)"))
        while self._running:
            result = run_due_jobs()
            reconcile_run_outcomes()
            if result.enqueued or result.skipped or result.errors:
                self.stdout.write(f"  {result}")
            if options["once"]:
                break
            # Sleep in short slices so SIGTERM is honored promptly.
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)
        self.stdout.write("scheduler_beat: stopped")
