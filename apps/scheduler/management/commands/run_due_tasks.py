"""Fire all due schedules once (system-cron / systemd-timer path).

    * * * * * cd /app && python manage.py run_due_tasks

Idempotent and safe to run every minute. Use exactly one trigger per
deployment (this, the /scheduler/tick/ POST, or scheduler_beat) — the atomic
claim in run_due_jobs makes an accidental overlap safe rather than duplicating,
but running two on purpose just wastes work.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.scheduler.services import reconcile_run_outcomes, run_due_jobs


class Command(BaseCommand):
    help = "Enqueue any scheduled jobs whose next run is due."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--no-reconcile",
            action="store_true",
            help="Skip promoting finished runs to success/failed.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        result = run_due_jobs()
        if not options["no_reconcile"]:
            reconcile_run_outcomes()
        self.stdout.write(self.style.SUCCESS(f"run_due_tasks: {result}"))
