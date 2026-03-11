"""Management command to prune old activity log entries."""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Prune activity log to keep it within the configured max rows."

    def handle(self, **options):
        from apps.activity.models import RequestLog

        max_rows = getattr(settings, "ACTIVITY_MAX_ROWS", 5000)
        count = RequestLog.objects.count()

        if count <= max_rows:
            self.stdout.write(f"Activity log has {count} rows (max {max_rows}). No pruning needed.")
            return

        # Get the pk of the oldest row to keep, then delete everything older
        cutoff_pk = (
            RequestLog.objects.order_by("-timestamp").values_list("pk", flat=True)[max_rows - 1]
        )
        deleted, _ = RequestLog.objects.filter(pk__lt=cutoff_pk).delete()
        self.stdout.write(f"Pruned {deleted} activity log rows (was {count}, max {max_rows}).")
