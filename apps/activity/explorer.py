"""Explorer registration for activity models."""

from django.utils import timezone

from apps.explorer.registry import explorer
from apps.smallstack.displays import StatsAccessory

from .admin import RequestLogAdmin
from .models import RequestLog

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
