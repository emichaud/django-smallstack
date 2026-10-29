"""Calendar widget for the central /smallstack/ dashboard — what's on today."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from apps.smallstack.displays import DashboardWidget

from .apps import CALENDAR_ICON


class CalendarDashboardWidget(DashboardWidget):
    title = "Calendar"
    icon = CALENDAR_ICON.replace('width="20" height="20"', 'width="22" height="22"')
    order = 36  # after Blog (34) and MCP (35)
    url_name = "calendar_index"

    def get_data(self, model_class: type | None = None) -> dict[str, Any]:
        from django.utils import timezone

        from .core import iter_calendars
        from .models import SavedCalendarView

        cals = list(iter_calendars())
        if not cals:
            return {
                "headline": "No calendars",
                "detail": "Declare one with @calendar_dataset",
                "status": "degraded",
            }
        today = timezone.localdate()
        on_today = 0
        for cal in cals:
            try:
                on_today += cal.count(today, today + timedelta(days=1))
            except Exception:  # noqa: BLE001 — one broken calendar must not blank the tile
                continue
        n_views = SavedCalendarView.objects.count()
        detail = f"{on_today} event{'' if on_today == 1 else 's'} today"
        if n_views:
            detail += f" · {n_views} saved view{'' if n_views == 1 else 's'}"
        return {
            "headline": f"{len(cals)} calendar{'' if len(cals) == 1 else 's'}",
            "detail": detail,
            "status": "operational",
        }
