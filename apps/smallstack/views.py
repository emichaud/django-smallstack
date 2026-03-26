"""Views for SmallStack dashboard and SQLite database backup management."""

import os
import time

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic import TemplateView

from .mixins import StaffRequiredMixin
from .models import BackupRecord
from .pagination import paginate_queryset


class LayoutPreviewView(StaffRequiredMixin, TemplateView):
    """Staff-only page to preview different navigation layout combinations."""

    template_name = "smallstack/layout_preview.html"


class NavGuideView(StaffRequiredMixin, TemplateView):
    """Staff-only guide explaining sidebar, topbar, and contextual navigation."""

    template_name = "smallstack/nav_guide.html"


class SmallStackDashboardView(StaffRequiredMixin, TemplateView):
    """Staff-only dashboard with at-a-glance widgets from each app."""

    template_name = "smallstack/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["widgets"] = self._build_widgets()
        return context

    # SVG icons for dashboard widgets (long paths, suppress line-length lint)
    _ICONS = {
        "status": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>',  # noqa: E501
        "activity": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>',  # noqa: E501
        "users": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>',  # noqa: E501
        "backups": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>',  # noqa: E501
        "help": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>',  # noqa: E501
        "explorer": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z"/></svg>',  # noqa: E501
    }

    def _build_widgets(self):
        widgets = []
        now = timezone.now()

        # Status widget (heartbeat)
        try:
            from apps.heartbeat.views import _calc_uptime, _get_status_data

            status_data = _get_status_data()
            uptime_24h = _calc_uptime(24)
            widgets.append(
                {
                    "title": "Status",
                    "icon": self._ICONS["status"],
                    "headline": status_data.get("status_label", "Unknown"),
                    "detail": f"{uptime_24h}% uptime (24h)" if uptime_24h is not None else "No data",
                    "url_name": "heartbeat:dashboard",
                    "status": status_data.get("status", "unknown"),
                }
            )
        except Exception:
            pass

        # Activity widget
        try:
            from apps.activity.models import RequestLog

            total = RequestLog.objects.count()
            twenty_four_hours_ago = now - timezone.timedelta(hours=24)
            recent = RequestLog.objects.filter(timestamp__gte=twenty_four_hours_ago).count()
            widgets.append(
                {
                    "title": "Activity",
                    "icon": self._ICONS["activity"],
                    "headline": f"{total:,} requests",
                    "detail": f"{recent:,} in last 24h",
                    "url_name": "activity:dashboard",
                }
            )
        except Exception:
            pass

        # Users widget
        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            active_count = User.objects.filter(is_active=True).count()
            thirty_days_ago = now - timezone.timedelta(days=30)
            new_count = User.objects.filter(date_joined__gte=thirty_days_ago).count()
            widgets.append(
                {
                    "title": "Users",
                    "icon": self._ICONS["users"],
                    "headline": f"{active_count} active",
                    "detail": f"{new_count} new (30d)",
                    "url_name": "manage/users-list",
                }
            )
        except Exception:
            pass

        # Backups widget
        try:
            latest = BackupRecord.objects.filter(status="success").first()
            total_backups = BackupRecord.objects.filter(status="success", pruned_at__isnull=True).count()
            if latest:
                headline = latest.created_at.strftime("%b %d, %I:%M %p")
            else:
                headline = "No backups"
            widgets.append(
                {
                    "title": "Backups",
                    "icon": self._ICONS["backups"],
                    "headline": headline,
                    "detail": f"{total_backups} stored",
                    "url_name": "smallstack:backups",
                }
            )
        except Exception:
            pass

        # Help & Docs widget
        try:
            from apps.help.utils import get_all_sections

            sections = get_all_sections()
            article_count = sum(len(s.get("pages", [])) for s in sections)
            section_count = len(sections)
            widgets.append(
                {
                    "title": "Help & Docs",
                    "icon": self._ICONS["help"],
                    "headline": f"{article_count} article{'s' if article_count != 1 else ''}",
                    "detail": f"Across {section_count} section{'s' if section_count != 1 else ''}",
                    "url_name": "help:section_index",
                    "url_kwargs": {"section": "smallstack"},
                }
            )
        except Exception:
            pass

        # Explorer widget
        try:
            from apps.explorer.registry import explorer_registry

            model_count = len(explorer_registry.get_models())
            widgets.append(
                {
                    "title": "Explorer",
                    "icon": self._ICONS["explorer"],
                    "headline": f"{model_count} model{'s' if model_count != 1 else ''}",
                    "detail": "Registered for exploration",
                    "url_name": "explorer-index",
                }
            )
        except Exception:
            pass

        for w in widgets:
            w["icon"] = mark_safe(w["icon"])
            w["url"] = reverse(w.pop("url_name"), kwargs=w.pop("url_kwargs", None))
        return widgets


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
