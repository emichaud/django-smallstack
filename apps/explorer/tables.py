"""django-tables2 table for the Explorer index page."""

import django_tables2 as tables
from django.utils.html import format_html
from django.utils.safestring import mark_safe

LOCK_SVG = (
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"'
    ' style="vertical-align:-2px;margin-left:0.4rem;opacity:0.5;">'
    '<path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2'
    "v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1"
    " 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39"
    '-3.1 3.1-3.1s3.1 1.39 3.1 3.1v2z"/></svg>'
)


class ExplorerModelTable(tables.Table):
    """Sortable table of all registered explorer models."""

    model = tables.Column(accessor="verbose_name_plural", verbose_name="Model", orderable=True)
    app = tables.Column(accessor="app_label", verbose_name="App", orderable=True)
    group = tables.Column(accessor="group", verbose_name="Group", orderable=True)
    records = tables.Column(accessor="count", verbose_name="Records", orderable=True)
    access = tables.Column(accessor="readonly", verbose_name="Access", orderable=True)

    class Meta:
        attrs = {"class": "crud-table"}
        order_by = "model"

    def render_model(self, record):
        lock = mark_safe(LOCK_SVG) if record["readonly"] else ""
        return format_html(
            '<a href="{}">{}</a>{}',
            record["list_url"],
            record["verbose_name_plural"],
            lock,
        )

    def render_app(self, record):
        return record["app_label"]

    def render_group(self, record):
        return record["group"]

    def render_records(self, record):
        return format_html(
            '<span style="font-weight:600;font-variant-numeric:tabular-nums;color:var(--primary);">{}</span>',
            record["count"],
        )

    def render_access(self, record):
        if record["readonly"]:
            return mark_safe(
                '<span style="color:var(--body-quiet-color);font-size:0.85rem;">Read-only</span>',
            )
        return mark_safe(
            '<span style="font-size:0.85rem;">Full</span>',
        )

    def value_model(self, record):
        return record["verbose_name_plural"]

    def value_app(self, record):
        return record["app_label"]

    def value_group(self, record):
        return record["group"]

    def value_records(self, record):
        return record["count"]

    def value_access(self, record):
        return "readonly" if record["readonly"] else "full"
