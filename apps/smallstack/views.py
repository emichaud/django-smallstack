"""Views for SmallStack dashboard and SQLite database backup management."""

import os
import time

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views import View
from django.views.generic import TemplateView

from .dashboard import DashboardWidgetsMixin
from .mixins import StaffRequiredMixin
from .models import BackupRecord
from .pagination import paginate_queryset


class LayoutPreviewView(StaffRequiredMixin, TemplateView):
    """Staff-only page to preview different navigation layout combinations."""

    template_name = "smallstack/layout_preview.html"


class NavGuideView(StaffRequiredMixin, TemplateView):
    """Staff-only guide explaining sidebar, topbar, and contextual navigation."""

    template_name = "smallstack/nav_guide.html"


class SmallStackDashboardView(StaffRequiredMixin, DashboardWidgetsMixin, TemplateView):
    """Staff-only dashboard with at-a-glance widgets from each app."""

    template_name = "smallstack/dashboard.html"


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


def _prune_backups(triggered_by="manual", keep=None):
    """Remove oldest backups beyond the keep count (defaults to BACKUP_RETENTION)."""
    from pathlib import Path

    from django.utils import timezone

    if keep is None:
        keep = getattr(settings, "BACKUP_RETENTION", None)
    if keep is None:
        return []

    backup_dir = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
    if not backup_dir.exists():
        return []

    backups = sorted(backup_dir.glob("db-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    to_remove = backups[keep:]
    pruned = []
    for path in to_remove:
        path.unlink()
        # Mark the original success record as pruned
        updated = BackupRecord.objects.filter(filename=path.name, status="success", pruned_at__isnull=True).update(
            pruned_at=timezone.now()
        )
        if not updated:
            # No matching record found — create one for tracking
            BackupRecord.objects.create(
                filename=path.name,
                file_size=0,
                duration_ms=0,
                status="success",
                triggered_by=triggered_by,
                pruned_at=timezone.now(),
            )
        pruned.append(path.name)
    return pruned


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
        _prune_backups(triggered_by=triggered_by)
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
        page_obj = paginate_queryset(records, self.request, page_size=5)
        context["backup_records"] = page_obj
        context["page_obj"] = page_obj
        context["backup_dir"] = getattr(settings, "BACKUP_DIR", str(settings.BASE_DIR / "backups"))

        # Dashboard stats
        from django.db.models import Avg, Count, Q, Sum
        from django.utils import timezone

        stats = records.aggregate(
            total=Count("pk"),
            success_count=Count("pk", filter=Q(status="success", pruned_at__isnull=True)),
            failed_count=Count("pk", filter=Q(status="failed")),
            pruned_count=Count("pk", filter=Q(pruned_at__isnull=False)),
            avg_duration=Avg("duration_ms", filter=Q(status="success")),
            total_size=Sum("file_size", filter=Q(status="success", pruned_at__isnull=True)),
        )
        twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
        context["recent_count"] = records.filter(
            status="success", pruned_at__isnull=True, created_at__gte=twenty_four_hours_ago
        ).count()
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

        # Download feature flag
        context["backup_download_enabled"] = getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True)

        # Backup settings for Configuration tab
        context["settings_info"] = {
            "backup_retention": getattr(settings, "BACKUP_RETENTION", 10),
            "backup_cron_enabled": getattr(settings, "BACKUP_CRON_ENABLED", False),
            "backup_download_enabled": getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True),
        }

        # Files on disk for Files tab
        from datetime import datetime
        from pathlib import Path

        backup_path = Path(getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        backup_files = []
        if backup_path.exists():
            for f in sorted(backup_path.glob("db-*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
                stat = f.stat()
                backup_files.append(
                    {
                        "filename": f.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime),
                    }
                )
        context["backup_files"] = backup_files

        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if getattr(request, "htmx", False):
            # If paging the backup history table, return only that partial
            if request.GET.get("page"):
                return TemplateResponse(request, "smallstack/partials/backup_history.html", context)
            return TemplateResponse(request, "smallstack/partials/backup_page_content.html", context)
        return TemplateResponse(request, self.template_name, context)


class BackupDetailView(StaffRequiredMixin, TemplateView):
    """Detail page for a single backup record."""

    template_name = "smallstack/backup_detail.html"

    def get_context_data(self, **kwargs):
        from django.shortcuts import get_object_or_404

        context = super().get_context_data(**kwargs)
        record = get_object_or_404(BackupRecord, pk=self.kwargs["pk"])
        context["record"] = record
        context["backup_download_enabled"] = getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True)

        # Build timeline events
        events = []
        events.append(
            {
                "icon": "backup",
                "label": "Backup created",
                "detail": f"{record.get_triggered_by_display()} trigger",
                "timestamp": record.created_at,
                "status": "success" if record.status == "success" else "failed",
            }
        )
        if record.status == "failed":
            events.append(
                {
                    "icon": "error",
                    "label": "Backup failed",
                    "detail": record.error_message or "Unknown error",
                    "timestamp": record.created_at,
                    "status": "failed",
                }
            )
        if record.is_pruned:
            events.append(
                {
                    "icon": "pruned",
                    "label": "File pruned",
                    "detail": "Removed by retention policy",
                    "timestamp": record.pruned_at,
                    "status": "pruned",
                }
            )
        elif record.status == "success" and not record.file_exists:
            events.append(
                {
                    "icon": "warning",
                    "label": "File missing",
                    "detail": "Backup file not found on disk",
                    "timestamp": None,
                    "status": "warning",
                }
            )
        context["events"] = events
        return context


class BackupStatDetailView(StaffRequiredMixin, View):
    """Return a partial table of backup records filtered by stat type."""

    def get(self, request, stat):
        from django.utils import timezone

        twenty_four_hours_ago = timezone.now() - timezone.timedelta(hours=24)
        filters = {
            "recent": {"status": "success", "pruned_at__isnull": True, "created_at__gte": twenty_four_hours_ago},
            "success": {"status": "success", "pruned_at__isnull": True},
            "failed": {"status": "failed"},
            "pruned": {"pruned_at__isnull": False},
        }
        qs_filter = filters.get(stat)
        if qs_filter is None:
            raise Http404
        records = BackupRecord.objects.filter(**qs_filter)[:100]
        from django.shortcuts import render

        return render(
            request,
            "smallstack/partials/backup_stat_detail.html",
            {
                "records": records,
                "backup_download_enabled": getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True),
            },
        )


class BackupNowView(StaffRequiredMixin, View):
    """Create a backup on persistent storage without downloading."""

    def post(self, request):
        db_info = _get_db_info()
        if not db_info["is_sqlite"]:
            messages.error(request, "Backup is only available for SQLite databases.")
            return redirect("smallstack:backups")

        record = _do_backup(triggered_by="command")
        if record.status == "failed":
            messages.error(request, f"Backup failed: {record.error_message}")
        else:
            messages.success(request, f"Backup created: {record.filename} ({_format_size(record.file_size)})")
        return redirect("smallstack:backups")


class BackupDownloadView(StaffRequiredMixin, View):
    """Create a backup and download it immediately."""

    def post(self, request):
        if not getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True):
            return HttpResponseForbidden("Downloads are disabled.")

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

        response = FileResponse(open(file_path, "rb"), content_type="application/x-sqlite3")
        response["Content-Disposition"] = f'attachment; filename="{record.filename}"'
        return response


class BackupFileDownloadView(StaffRequiredMixin, View):
    """Download an existing backup file by filename."""

    def get(self, request, filename):
        if not getattr(settings, "BACKUP_DOWNLOAD_ENABLED", True):
            return HttpResponseForbidden("Downloads are disabled.")

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
