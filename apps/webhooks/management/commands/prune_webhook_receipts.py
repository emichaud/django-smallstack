"""History retention: delete inbound WebhookReceipt rows older than a cutoff.

    15 3 * * * cd /app && python manage.py prune_webhook_receipts

The inbound receiver is a public route; without retention its receipts grow
without bound. Defaults to ``SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS`` (30).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from apps.webhooks.models import WebhookReceipt


class Command(BaseCommand):
    help = "Delete inbound webhook receipts older than --keep-days."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--keep-days",
            type=int,
            default=None,
            help="Retention window in days (default: SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS, 30).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        keep = options["keep_days"]
        if keep is None:
            keep = int(getattr(settings, "SMALLSTACK_WEBHOOK_RECEIPT_RETENTION_DAYS", 30))
        cutoff = timezone.now() - timedelta(days=max(1, keep))
        deleted, _ = WebhookReceipt.objects.filter(received_at__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(f"prune_webhook_receipts: deleted {deleted} receipt(s) before {cutoff:%Y-%m-%d}")
        )
