"""Reusable django-tables2 column types for SmallStack CRUD views.

.. deprecated::
    The built-in TableDisplay now supports column sorting via HTMX.
    Prefer TableDisplay over Table2Display and these column helpers.
    These classes remain available for backward compatibility but will
    be removed in a future release.

Provides composable columns that integrate with the CRUDView system:

    from apps.smallstack.tables import BooleanColumn, DetailLinkColumn, ActionsColumn

    class UserTable(tables.Table):
        username = DetailLinkColumn(url_base="manage/users")
        is_staff = BooleanColumn()
        actions = ActionsColumn(url_base="manage/users")

        class Meta:
            model = User
            fields = ("username", "email", "is_staff", "is_active")
            attrs = {"class": "crud-table"}
"""

import warnings

import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe


class BooleanColumn(tables.Column):
    """Renders True/False as ✓/— with theme-aware color."""

    def __init__(self, true_mark="✓", false_mark="—", **kwargs):
        warnings.warn(
            "BooleanColumn is deprecated. Use TableDisplay with field_transforms instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        kwargs.setdefault("attrs", {})
        kwargs["attrs"].setdefault("td", {"style": "text-align: center;"})
        kwargs["attrs"].setdefault("th", {"style": "text-align: center;"})
        super().__init__(**kwargs)
        self.true_mark = true_mark
        self.false_mark = false_mark

    def render(self, value):
        if value:
            return format_html(
                '<span style="color: var(--primary); font-weight: 600;">{}</span>',
                self.true_mark,
            )
        return format_html(
            '<span style="color: var(--body-quiet-color);">{}</span>',
            self.false_mark,
        )


class DetailLinkColumn(tables.Column):
    """Wraps cell value in a link to a CRUD view (detail by default).

    Usage:
        username = DetailLinkColumn(url_base="manage/users")
        username = DetailLinkColumn(url_base="manage/users", link_view="update")
    """

    def __init__(
        self,
        url_base: str,
        link_view: str = "detail",
        namespace: str | None = None,
        **kwargs,
    ):
        warnings.warn(
            "DetailLinkColumn is deprecated. Use TableDisplay with link_field instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(linkify=False, **kwargs)
        self.url_base = url_base
        self.link_view = link_view
        self.namespace = namespace

    def _reverse(self, url_name: str, **kwargs) -> str:
        if self.namespace:
            return reverse(f"{self.namespace}:{url_name}", **kwargs)
        return reverse(url_name, **kwargs)

    def render(self, value, record):
        url = self._reverse(f"{self.url_base}-{self.link_view}", kwargs={"pk": record.pk})
        return format_html('<a href="{}">{}</a>', url, value)


class ActionsColumn(tables.Column):
    """Renders Edit/Delete action icons matching the CRUD table style.

    Usage:
        actions = ActionsColumn(url_base="manage/users")
        actions = ActionsColumn(url_base="manage/users", edit=False)  # delete only
        actions = ActionsColumn(url_base="manage/users", delete=False)  # edit only
    """

    EDIT_SVG = mark_safe(
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">'
        '<path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z'
        "M20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34"
        "c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"
        '"/></svg>'
    )
    DELETE_SVG = mark_safe(
        '<svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">'
        '<path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12z'
        'M19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>'
    )

    def __init__(
        self,
        url_base: str,
        edit: bool = True,
        delete: bool = True,
        namespace: str | None = None,
        **kwargs,
    ):
        warnings.warn(
            "ActionsColumn is deprecated. Use TableDisplay with CRUDView actions instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        kwargs["empty_values"] = ()  # Always render, even if no value
        kwargs["orderable"] = False
        kwargs["verbose_name"] = ""
        kwargs.setdefault("attrs", {})
        kwargs["attrs"].setdefault("td", {"style": "text-align: right; white-space: nowrap;"})
        kwargs["attrs"].setdefault("th", {"style": "text-align: right;"})
        super().__init__(**kwargs)
        self.url_base = url_base
        self.show_edit = edit
        self.show_delete = delete
        self.namespace = namespace

    def _reverse(self, url_name: str, **kwargs) -> str:
        if self.namespace:
            return reverse(f"{self.namespace}:{url_name}", **kwargs)
        return reverse(url_name, **kwargs)

    def render(self, record):
        links = []
        style = "display: inline-flex; align-items: center; gap: 0.3rem; margin-left: 0.75rem;"

        if self.show_edit:
            url = self._reverse(f"{self.url_base}-update", kwargs={"pk": record.pk})
            links.append(
                format_html(
                    '<a href="{}" style="{}" title="Edit">{}</a>',
                    url,
                    style,
                    self.EDIT_SVG,
                )
            )

        if self.show_delete:
            url = self._reverse(f"{self.url_base}-delete", kwargs={"pk": record.pk})
            links.append(
                format_html(
                    '<a href="{}" class="crud-action-delete" style="{}" title="Delete"'
                    " onclick=\"event.preventDefault();crudDeleteModal(this,'{}')\""
                    ' data-delete-url="{}">{}</a>',
                    url,
                    style,
                    record,
                    url,
                    self.DELETE_SVG,
                )
            )

        return format_html("".join("{}") * len(links), *links) if links else ""
