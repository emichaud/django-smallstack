"""Views for SQLite database backup management."""

import os
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from .models import BackupRecord


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that restricts access to staff users."""

    def test_func(self):
        return self.request.user.is_staff


def _get_db_info():
    """Return database engine and file path info."""
    db = settings.DATABASES["default"]
    engine = db["ENGINE"]
    is_sqlite = "sqlite3" in engine
    db_path = db.get("NAME", "")
    db_size = 0
    if is_sqlite and db_path and os.path.exists(db_path):
        db_size = os.path.getsize(db_path)
    return {
        "engine": engine.split(".")[-1],
        "is_sqlite": is_sqlite,
        "db_path": db_path,
        "db_size": db_size,
    }


def _do_backup(triggered_by="manual"):
    """Perform a SQLite backup and return the BackupRecord."""
    import sqlite3
    from datetime import datetime
    from pathlib import Path

    db = settings.DATABASES["default"]
    db_path = db["NAME"]
    backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"db-{timestamp}.sqlite3"
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

        record = BackupRecord.objects.create(
            filename=filename,
            file_size=file_size,
            duration_ms=duration_ms,
            status="success",
            triggered_by=triggered_by,
        )
        return record
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        record = BackupRecord.objects.create(
            filename="",
            file_size=0,
            duration_ms=duration_ms,
            status="failed",
            error_message=str(e),
            triggered_by=triggered_by,
        )
        return record


class BackupPageView(StaffRequiredMixin, TemplateView):
    """Staff-only backup status page."""

    template_name = "smallstack/backups.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        db_info = _get_db_info()
        context.update(db_info)
        context["backup_cron_enabled"] = getattr(settings, "BACKUP_CRON_ENABLED", False)
        context["backup_records"] = BackupRecord.objects.all()[:50]
        context["backup_dir"] = getattr(settings, "BACKUP_DIR", str(settings.BASE_DIR / "backups"))
        return context


class BackupDownloadView(StaffRequiredMixin, View):
    """Create a backup and download it immediately."""

    def post(self, request):
        db_info = _get_db_info()
        if not db_info["is_sqlite"]:
            messages.error(request, "Backup download is only available for SQLite databases.")
            return redirect("smallstack:backups")

        record = _do_backup(triggered_by="manual")
        if record.status == "failed":
            messages.error(request, f"Backup failed: {record.error_message}")
            return redirect("smallstack:backups")

        from pathlib import Path

        backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        file_path = backup_dir / record.filename

        messages.success(request, f"Backup created: {record.filename} ({_format_size(record.file_size)})")
        response = FileResponse(open(file_path, "rb"), content_type="application/x-sqlite3")
        response["Content-Disposition"] = f'attachment; filename="{record.filename}"'
        return response


class BackupFileDownloadView(StaffRequiredMixin, View):
    """Download an existing backup file by filename."""

    def get(self, request, filename):
        from pathlib import Path

        # Prevent path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            raise Http404

        backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        file_path = backup_dir / filename

        if not file_path.exists():
            raise Http404

        response = FileResponse(open(file_path, "rb"), content_type="application/x-sqlite3")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


def _format_size(size_bytes):
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
