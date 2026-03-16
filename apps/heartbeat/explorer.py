"""Explorer registration for heartbeat models."""

from apps.explorer.registry import explorer

from .admin import (
    HeartbeatAdmin,
    HeartbeatDailyAdmin,
    HeartbeatEpochAdmin,
    MaintenanceWindowAdmin,
)
from .models import Heartbeat, HeartbeatDaily, HeartbeatEpoch, MaintenanceWindow

explorer.register(Heartbeat, HeartbeatAdmin, group="Monitoring")
explorer.register(HeartbeatEpoch, HeartbeatEpochAdmin, group="Monitoring")
explorer.register(HeartbeatDaily, HeartbeatDailyAdmin, group="Monitoring")
explorer.register(MaintenanceWindow, MaintenanceWindowAdmin, group="Monitoring")
