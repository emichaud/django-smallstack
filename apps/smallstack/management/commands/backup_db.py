"""Management command for SQLite database backup."""

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.mail import mail_admins
from django.core.management.base import BaseCommand

from apps.smallstack.models import BackupRecord
from apps.smallstack.views import _prune_backups


class Command(BaseCommand):
    help = "Create a safe SQLite database backup"

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep",
            type=int,
            default=None,
            help="Keep only the N most recent backups, prune the rest",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help="Override destination file path",
        )

    def handle(self, *args, **options):
        db = settings.DATABASES["default"]
        engine = db["ENGINE"]

        if "sqlite3" not in engine:
            self.stderr.write(
                self.style.ERROR(
                    "This command only supports SQLite databases. PostgreSQL backup is coming in a future release."
                )
            )
            return

        db_path = db["NAME"]
        if not os.path.exists(db_path):
            self.stderr.write(self.style.ERROR(f"Database file not found: {db_path}"))
            return

        backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"db-{timestamp}.sqlite3"

        if options["output"]:
            dest_path = Path(options["output"])
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            filename = dest_path.name
        else:
            dest_path = backup_dir / filename

        start = time.monotonic()
        try:
            source = sqlite3.connect(db_path)
            dest = sqlite3.connect(str(dest_path))
            with dest:
                source.backup(dest)
            source.close()
            dest.close()
            duration_ms = int((time.monotonic() - start) * 1000)
            file_size = os.path.getsize(dest_path)

            BackupRecord.objects.create(
                filename=filename,
                file_size=file_size,
                duration_ms=duration_ms,
                status="success",
                triggered_by="command",
            )

            self.stdout.write(self.style.SUCCESS(f"Backup created: {dest_path} ({file_size:,} bytes, {duration_ms}ms)"))

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            BackupRecord.objects.create(
                filename="",
                file_size=0,
                duration_ms=duration_ms,
                status="failed",
                error_message=str(e),
                triggered_by="command",
            )
            self.stderr.write(self.style.ERROR(f"Backup failed: {e}"))

            # Notify admins if email is configured
            if getattr(settings, "ADMINS", []):
                try:
                    mail_admins(
                        subject="Database backup failed",
                        message=f"Backup failed at {datetime.now()}\n\nError: {e}",
                        fail_silently=True,
                    )
                except Exception:
                    pass
            return

        # Prune old backups (--keep overrides BACKUP_RETENTION)
        pruned = _prune_backups(triggered_by="command", keep=options["keep"])

        for name in pruned:
            self.stdout.write(f"Pruned: {name}")
        if pruned:
            self.stdout.write(self.style.SUCCESS(f"Pruned {len(pruned)} old backup(s)"))
