"""django-tables2 table definitions for the heartbeat app."""

import django_tables2 as tables
from django.utils.html import format_html
from django.utils.timezone import localtime

from .models import Heartbeat


class HeartbeatTable(tables.Table):
    """Sortable table for heartbeat records."""

    timestamp = tables.Column(verbose_name="Time")
    status = tables.Column(verbose_name="Status")
    response_time_ms = tables.Column(verbose_name="Response")
    note = tables.Column(verbose_name="Note")

    class Meta:
        model = Heartbeat
        fields = ("timestamp", "status", "response_time_ms", "note")
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

    def render_status(self, value, record):
        if record.status == "ok":
            return format_html('<span style="color:var(--success-fg);font-weight:600;">{}</span>', "OK")
        return format_html('<span style="color:var(--error-fg);font-weight:600;">{}</span>', "FAIL")

    def render_response_time_ms(self, value):
        return format_html('<span style="font-size:0.85rem;">{}ms</span>', value)

    def render_note(self, value):
        if not value:
            return "—"
        truncated = value[:80] + "…" if len(value) > 80 else value
        return format_html(
            '<span style="font-size:0.85rem;color:var(--body-quiet-color);">{}</span>',
            truncated,
        )
