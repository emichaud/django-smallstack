"""Views for SQLite database backup management."""

import os
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import FileResponse, Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views import View
from django.views.generic import TemplateView

from .models import BackupRecord
from .pagination import paginate_queryset


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
        records = BackupRecord.objects.all()
        page_obj = paginate_queryset(records, self.request, page_size=15)
        context["backup_records"] = page_obj
        context["page_obj"] = page_obj
        context["backup_dir"] = getattr(settings, "BACKUP_DIR", str(settings.BASE_DIR / "backups"))

        # Dashboard stats
        from django.db.models import Avg, Count, Q, Sum
        from django.utils import timezone

        stats = records.aggregate(
            total=Count("pk"),
            success_count=Count("pk", filter=Q(status="success")),
            failed_count=Count("pk", filter=Q(status="failed")),
            pruned_count=Count("pk", filter=Q(status="pruned")),
            avg_duration=Avg("duration_ms", filter=Q(status="success")),
            total_size=Sum("file_size", filter=Q(status="success")),
        )
        twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
        context["recent_count"] = records.filter(status="success", created_at__gte=twenty_four_hours_ago).count()
        context["total_backups"] = stats["total"]
        context["success_count"] = stats["success_count"]
        context["failed_count"] = stats["failed_count"]
        context["pruned_count"] = stats["pruned_count"]
        context["avg_duration"] = round(stats["avg_duration"] or 0)
        context["total_backup_size"] = stats["total_size"] or 0

        # Admin notification info
        admins = getattr(settings, "ADMINS", [])
        context["admins"] = admins
        email_backend = getattr(settings, "EMAIL_BACKEND", "")
        context["email_is_console"] = "console" in email_backend

        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if getattr(request, "htmx", False):
            return TemplateResponse(
                request, "smallstack/partials/backup_history.html", context
            )
        return TemplateResponse(request, self.template_name, context)


class BackupStatDetailView(StaffRequiredMixin, View):
    """Return a partial table of backup records filtered by stat type."""

    def get(self, request, stat):
        from django.utils import timezone

        filters = {
            "recent": {"status": "success", "created_at__gte": timezone.now() - timezone.timedelta(hours=24)},
            "success": {"status": "success"},
            "failed": {"status": "failed"},
            "pruned": {"status": "pruned"},
        }
        qs_filter = filters.get(stat)
        if qs_filter is None:
            raise Http404
        records = BackupRecord.objects.filter(**qs_filter)[:100]
        from django.shortcuts import render

        return render(request, "smallstack/partials/backup_stat_detail.html", {"records": records})


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
