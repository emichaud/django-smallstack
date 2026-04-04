"""Standalone dashboard widgets that aren't attached to Explorer models."""

from apps.smallstack.displays import DashboardWidget


class BackupsDashboardWidget(DashboardWidget):
    title = "Backups"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>'
    )
    order = 40
    url_name = "smallstack:backups"

    def get_data(self, model_class=None):
        from apps.smallstack.models import BackupRecord

        latest = BackupRecord.objects.filter(status="success").first()
        total_backups = BackupRecord.objects.filter(status="success", pruned_at__isnull=True).count()
        if latest:
            headline = latest.created_at.strftime("%b %d, %I:%M %p")
        else:
            headline = "No backups"
        return {"headline": headline, "detail": f"{total_backups} stored"}


class HelpDashboardWidget(DashboardWidget):
    title = "Help & Docs"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 '
        '0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>'
    )
    order = 50
    url_name = "help:section_index"
    url_kwargs = {"section": "smallstack"}

    def get_data(self, model_class=None):
        from apps.help.utils import get_all_sections

        sections = get_all_sections()
        article_count = sum(len(s.get("pages", [])) for s in sections)
        section_count = len(sections)
        return {
            "headline": f"{article_count} article{'s' if article_count != 1 else ''}",
            "detail": f"Across {section_count} section{'s' if section_count != 1 else ''}",
        }
