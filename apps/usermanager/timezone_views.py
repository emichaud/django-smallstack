"""User Timezone Dashboard — shows team timezone distribution and local times."""

import zoneinfo
from datetime import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.views.generic import TemplateView
from django_tables2 import RequestConfig

from apps.profile.models import TIMEZONE_CHOICES
from apps.smallstack.mixins import StaffRequiredMixin

from .tables import TimezoneTable

User = get_user_model()


class TimezoneDashboardView(StaffRequiredMixin, TemplateView):
    template_name = "usermanager/timezone_dashboard.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["usermanager/_tz_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now_utc = datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
        server_tz_name = settings.TIME_ZONE
        server_tz = zoneinfo.ZoneInfo(server_tz_name)

        # Build user timezone data
        users = User.objects.filter(is_active=True).select_related("profile").order_by("username")

        user_rows = []
        tz_groups = {}  # tz_name -> list of users
        region_counts = {}  # region -> count

        for user in users:
            profile = getattr(user, "profile", None)
            tz_name = (profile.timezone if profile and profile.timezone else "") or server_tz_name
            tz = zoneinfo.ZoneInfo(tz_name)
            local_now = now_utc.astimezone(tz)
            offset = local_now.utcoffset()
            offset_hours = offset.total_seconds() / 3600
            # Format offset as +/-HH:MM
            sign = "+" if offset_hours >= 0 else "-"
            abs_hours = abs(offset_hours)
            offset_str = f"UTC{sign}{int(abs_hours)}:{int((abs_hours % 1) * 60):02d}"

            is_workday = _is_workday(local_now)
            is_custom = bool(profile and profile.timezone)
            region = _get_region(tz_name)

            row = {
                "user": user,
                "tz_name": tz_name,
                "tz_display": _tz_display_name(tz_name),
                "local_time": local_now,
                "offset_str": offset_str,
                "offset_hours": offset_hours,
                "is_workday": is_workday,
                "is_custom": is_custom,
                "region": region,
                "is_staff": user.is_staff,
            }
            user_rows.append(row)

            # Group by timezone
            if tz_name not in tz_groups:
                tz_groups[tz_name] = {
                    "tz_name": tz_name,
                    "tz_display": _tz_display_name(tz_name),
                    "local_time": local_now,
                    "offset_str": offset_str,
                    "offset_hours": offset_hours,
                    "is_workday": is_workday,
                    "users": [],
                }
            tz_groups[tz_name]["users"].append(user)

            # Count by region
            region_counts[region] = region_counts.get(region, 0) + 1

        # Sort groups by UTC offset
        sorted_groups = sorted(tz_groups.values(), key=lambda g: g["offset_hours"])

        # Sort region counts
        sorted_regions = sorted(region_counts.items(), key=lambda r: -r[1])

        # Search filter
        search_query = self.request.GET.get("q", "").strip()
        if search_query:
            q_lower = search_query.lower()
            user_rows = [
                r
                for r in user_rows
                if q_lower in r["user"].username.lower()
                or q_lower in r["user"].get_full_name().lower()
                or q_lower in (r["user"].email or "").lower()
                or q_lower in r["tz_name"].lower()
                or q_lower in r["tz_display"].lower()
                or q_lower in r["region"].lower()
            ]

        # Build table — sorted by offset (west to east)
        sorted_rows = sorted(user_rows, key=lambda r: (r["offset_hours"], r["user"].username))
        table = TimezoneTable(sorted_rows)
        RequestConfig(self.request, paginate={"per_page": 10}).configure(table)

        # Unique regions for filter buttons
        regions = sorted(set(r["region"] for r in user_rows))

        context.update(
            {
                "now_utc": now_utc,
                "server_tz_name": server_tz_name,
                "server_time": now_utc.astimezone(server_tz),
                "user_rows": user_rows,
                "tz_groups": sorted_groups,
                "region_counts": sorted_regions,
                "total_users": len(user_rows),
                "unique_timezones": len(tz_groups),
                "table": table,
                "sorted_rows": sorted_rows,
                "regions": regions,
                "search_query": search_query,
            }
        )
        return context


def _is_workday(local_now):
    """Check if it's roughly working hours in the user's local time.

    Configurable via Django settings:
        WORK_HOURS_START  – hour (0-23) when work begins (default: 8)
        WORK_HOURS_END    – hour (0-23) when work ends (default: 18)
        WORK_DAYS         – tuple of weekday ints, 0=Mon … 6=Sun (default: (0,1,2,3,4))
    """
    work_days = getattr(settings, "WORK_DAYS", (0, 1, 2, 3, 4))
    start = getattr(settings, "WORK_HOURS_START", 8)
    end = getattr(settings, "WORK_HOURS_END", 18)
    if local_now.weekday() not in work_days:
        return False
    return start <= local_now.hour < end


def _tz_display_name(tz_name):
    """Get a friendly display name for a timezone."""
    # Search through TIMEZONE_CHOICES for the display name
    for item in TIMEZONE_CHOICES:
        if isinstance(item[1], list):
            for value, label in item[1]:
                if value == tz_name:
                    return label
        elif item[0] == tz_name:
            return item[1]
    # Fallback: strip prefix
    return tz_name.replace("_", " ").split("/")[-1]


def _get_region(tz_name):
    """Map a timezone name to a broad region."""
    if tz_name.startswith("America/"):
        return "Americas"
    if tz_name.startswith("Europe/"):
        return "Europe"
    if tz_name.startswith("Asia/"):
        return "Asia & Pacific"
    if tz_name.startswith("Australia/") or tz_name.startswith("Pacific/"):
        return "Asia & Pacific"
    if tz_name.startswith("Africa/"):
        return "Africa & Middle East"
    return "Other"
