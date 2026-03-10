"""django-tables2 table definitions for the User Manager CRUD views."""

import django_tables2 as tables
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.html import format_html

from apps.smallstack.tables import ActionsColumn, BooleanColumn, DetailLinkColumn

User = get_user_model()


class UserActionsColumn(ActionsColumn):
    """Actions column that hides delete for the current user."""

    def render(self, record, table):
        # If this row is the current user, only show edit
        if hasattr(table, "current_user_pk") and record.pk == table.current_user_pk:
            style = "display: inline-flex; align-items: center; gap: 0.3rem; margin-left: 0.75rem;"
            url = reverse(f"{self.url_base}-update", kwargs={"pk": record.pk})
            return format_html(
                '<a href="{}" style="{}" title="Edit">{}</a>',
                url, style, self.EDIT_SVG,
            )
        return super().render(record)


class UserTable(tables.Table):
    """Sortable user table for the Manage Users CRUD view."""

    username = DetailLinkColumn(url_base="manage/users", link_view="update", verbose_name="Username")
    email = tables.Column()
    name = tables.Column(empty_values=(), verbose_name="Name", orderable=False)
    timezone = tables.Column(empty_values=(), verbose_name="Timezone", orderable=False)
    is_staff = BooleanColumn(verbose_name="Staff")
    is_active = BooleanColumn(verbose_name="Active")
    actions = UserActionsColumn(url_base="manage/users")

    class Meta:
        model = User
        fields = ("username", "email", "name", "timezone", "is_staff", "is_active")
        order_by = "username"
        attrs = {"class": "crud-table"}

    def render_name(self, record):
        return record.get_full_name() or record.username

    def render_timezone(self, record):
        profile = getattr(record, "profile", None)
        tz = profile.timezone if profile and profile.timezone else ""
        if not tz:
            return format_html('<span style="color: var(--body-quiet-color);">{}</span>', "—")
        # Show the city part (e.g. "New York" from "America/New_York")
        city = tz.split("/")[-1].replace("_", " ")
        return format_html(
            '<span title="{}">{}</span>',
            tz, city,
        )


class TimezoneTable(tables.Table):
    """Table for timezone dashboard — shows users with their local times."""

    user = tables.Column(empty_values=(), verbose_name="User", orderable=True)
    timezone_display = tables.Column(empty_values=(), verbose_name="Timezone", orderable=True)
    local_time = tables.Column(empty_values=(), verbose_name="Local Time", orderable=True)
    offset = tables.Column(empty_values=(), verbose_name="UTC Offset", orderable=True)
    status = tables.Column(empty_values=(), verbose_name="Status", orderable=True)
    region = tables.Column(empty_values=(), verbose_name="Region", orderable=True)

    class Meta:
        attrs = {"class": "crud-table"}
        orderable = False

    def __init__(self, data, *args, **kwargs):
        # data is a list of dicts from the view
        super().__init__(data, *args, **kwargs)

    def render_user(self, record):
        user = record["user"]
        profile = getattr(user, "profile", None)
        initial = user.username[:1].upper()
        avatar_html = format_html(
            '<span style="display:inline-flex;align-items:center;justify-content:center;'
            'width:26px;height:26px;border-radius:50%;font-size:0.7rem;font-weight:700;'
            'background:color-mix(in srgb,var(--primary) 20%,var(--body-bg));color:var(--primary);'
            'flex-shrink:0;">{}</span>',
            initial,
        )
        if profile and profile.profile_photo:
            avatar_html = format_html(
                '<img src="{}" style="width:26px;height:26px;border-radius:50%;object-fit:cover;" alt="{}">',
                profile.profile_photo.url, user.username,
            )
        name = user.get_full_name() or user.username
        url = reverse("manage/users-update", kwargs={"pk": user.pk})
        staff_badge = ""
        if user.is_staff:
            staff_badge = format_html(
                ' <span style="font-size:0.65rem;padding:0.1rem 0.4rem;border-radius:3px;'
                'background:color-mix(in srgb,var(--primary) 15%,var(--body-bg));color:var(--primary);">{}</span>',
                "staff",
            )
        return format_html(
            '<div style="display:flex;align-items:center;gap:0.5rem;">'
            '{} <a href="{}">{}</a>{}</div>',
            avatar_html, url, name, staff_badge,
        )

    def render_timezone_display(self, record):
        return record["tz_display"]

    def render_local_time(self, record):
        lt = record["local_time"]
        time_12 = lt.strftime("%I:%M %p").lstrip("0")
        tz_abbr = lt.strftime("%Z")  # e.g. EDT, CDT, CET
        return format_html(
            '<span style="font-weight:600;font-variant-numeric:tabular-nums;">{} {}</span>',
            time_12, tz_abbr,
        )

    def render_offset(self, record):
        return record["offset_str"]

    def render_status(self, record):
        if record["is_workday"]:
            return format_html(
                '<span style="display:inline-flex;align-items:center;gap:0.35rem;">'
                '<span style="width:8px;height:8px;border-radius:50%;background:#28a745;display:inline-block;"></span>'
                '<span style="font-size:0.8rem;">{}</span></span>',
                "Working",
            )
        hour = record["local_time"].hour
        if hour >= 22 or hour < 6:
            return format_html(
                '<span style="display:inline-flex;align-items:center;gap:0.35rem;">'
                '<span style="width:8px;height:8px;border-radius:50%;background:#ffc107;display:inline-block;"></span>'
                '<span style="font-size:0.8rem;color:var(--body-quiet-color);">{}</span></span>',
                "Night",
            )
        return format_html(
            '<span style="display:inline-flex;align-items:center;gap:0.35rem;">'
            '<span style="width:8px;height:8px;border-radius:50%;'
            'background:color-mix(in srgb,var(--body-fg) 25%,var(--body-bg));'
            'display:inline-block;"></span>'
            '<span style="font-size:0.8rem;color:var(--body-quiet-color);">{}</span></span>',
            "Off Hours",
        )

    def render_region(self, record):
        return format_html(
            '<span style="font-size:0.8rem;">{}</span>',
            record.get("region", ""),
        )

    def value_local_time(self, record):
        return record["local_time"].strftime("%H:%M")

    def value_offset(self, record):
        return record["offset_hours"]

    def value_status(self, record):
        return "1-working" if record["is_workday"] else "2-off"

    def value_user(self, record):
        return record["user"].get_full_name() or record["user"].username


