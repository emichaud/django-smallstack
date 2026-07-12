"""Periodic retention sweep: prune over-window versions and expire idle docs.

Run on a schedule (cron / systemd timer), e.g. nightly:
    uv run python manage.py run_retention
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.runbook import retention


class Command(BaseCommand):
    help = "Prune superseded document versions and expire idle documents per retention policy."

    def handle(self, *args: Any, **options: Any) -> None:
        result = retention.run_sweep()
        self.stdout.write(
            self.style.SUCCESS(
                f"Retention sweep complete: pruned {result['pruned_versions']} version(s), "
                f"expired {result['expired_documents']} document(s)."
            )
        )
