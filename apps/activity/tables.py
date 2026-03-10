"""django-tables2 table definitions for the Activity app."""

import django_tables2 as tables
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import RequestLog


class RecentRequestsTable(tables.Table):
    """Sortable table for recent request logs."""

    timestamp = tables.Column(verbose_name="Time")
    method = tables.Column(verbose_name="Method")
    path = tables.Column(verbose_name="Path")
    status_code = tables.Column(verbose_name="Status")
    user = tables.Column(verbose_name="User", accessor="user__username", default="—")
    response_time_ms = tables.Column(verbose_name="Time (ms)")
    ip_address = tables.Column(verbose_name="IP", default="—")

    class Meta:
        model = RequestLog
        fields = ("timestamp", "method", "path", "status_code", "user", "response_time_ms", "ip_address")
        order_by = "-timestamp"
        attrs = {"class": "crud-table"}

    def render_timestamp(self, value):
        if value:
            local = localtime(value)
            return format_html(
                '<span style="white-space:nowrap;font-size:0.85rem;">{}</span>',
                local.strftime("%b %d %I:%M:%S %p %Z").lstrip("0"),
            )
        return "—"

    def render_method(self, value):
        return format_html("<code>{}</code>", value)

    def render_path(self, value):
        truncated = value[:60] + "…" if len(value) > 60 else value
        return format_html(
            '<span style="font-family:monospace;font-size:0.9rem;">{}</span>',
            truncated,
        )

    def render_status_code(self, value):
        color = ""
        if value >= 500:
            color = "color:var(--delete-button-bg,red);"
        elif value >= 400:
            color = "color:var(--message-warning-bg,orange);"
        return format_html('<span style="{}">{}</span>', color, value)

    def render_response_time_ms(self, value):
        return format_html('<span style="text-align:right;">{}</span>', value or "—")


class TopPathsTable(tables.Table):
    """Sortable table for top paths by hit count."""

    path = tables.Column(verbose_name="Path")
    hits = tables.Column(verbose_name="Hits")
    avg_time = tables.Column(verbose_name="Avg Time")

    class Meta:
        attrs = {"class": "crud-table"}
        order_by = "-hits"

    def render_path(self, value):
        return format_html(
            '<span style="font-family:monospace;font-size:0.9rem;">{}</span>',
            value,
        )

    def render_avg_time(self, value):
        return format_html("{}ms", round(value or 0))
