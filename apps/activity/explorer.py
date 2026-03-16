"""Explorer registration for activity models."""

from apps.explorer.registry import explorer

from .admin import RequestLogAdmin
from .models import RequestLog

explorer.register(RequestLog, RequestLogAdmin, group="Monitoring")
