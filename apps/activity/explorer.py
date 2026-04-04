"""Explorer registration for activity models."""

from django.utils import timezone

from apps.explorer.registry import explorer
from apps.smallstack.displays import DashboardWidget, StatsAccessory

from .admin import RequestLogAdmin
from .models import RequestLog


class ActivityDashboardWidget(DashboardWidget):
    title = "Activity"
    icon = (
        '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">'
        '<path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 '
        "3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 "
        "1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 "
        '5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/></svg>'
    )
    order = 20
    url_name = "activity:dashboard"

    def get_data(self, model_class=None):
        now = timezone.now()
        total = model_class.objects.count()
        recent = model_class.objects.filter(timestamp__gte=now - timezone.timedelta(hours=24)).count()
        return {
            "headline": f"{total:,} requests",
            "detail": f"{recent:,} in last 24h",
            # API-only extras (template ignores these):
            "extra": {"total": total, "last_24h": recent, "window_hours": 24},
        }


RequestLogAdmin.explorer_dashboard_widgets = [ActivityDashboardWidget()]

RequestLogAdmin.explorer_list_accessories = [
    StatsAccessory(
        stats=[
            {"label": "Total", "value": lambda qs: qs.count()},
            {
                "label": "Last 24h",
                "value": lambda qs: qs.filter(timestamp__gte=timezone.now() - timezone.timedelta(hours=24)).count(),
                "color": "var(--primary)",
            },
            {
                "label": "Errors",
                "value": lambda qs: qs.filter(status_code__gte=400).count(),
                "color": "var(--error-fg, #e74c3c)",
            },
        ]
    )
]

explorer.register(RequestLog, RequestLogAdmin, group="Monitoring")
