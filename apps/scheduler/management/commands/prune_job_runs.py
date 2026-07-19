"""History retention: delete ScheduledJobRun rows older than a cutoff.

    0 3 * * * cd /app && python manage.py prune_job_runs --keep-days 30

Heartbeat-style append-only history stays bounded without manual cleanup.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.scheduler.models import ScheduledJobRun


class Command(BaseCommand):
    help = "Delete scheduled-job run history older than --keep-days."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--keep-days", type=int, default=30, help="Retention window in days.")

    def handle(self, *args: Any, **options: Any) -> None:
        cutoff = timezone.now() - timedelta(days=max(1, options["keep_days"]))
        deleted, _ = ScheduledJobRun.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"prune_job_runs: deleted {deleted} run(s) before {cutoff:%Y-%m-%d}"))
