"""URL configuration for the heartbeat app."""

from django.urls import path

from .views import (
    HeartbeatDashboardView,
    MonitorDetailView,
    MonitoredEndpointCRUDView,
    MonitoredSurfaceCRUDView,
    SLADetailView,
    StatusDevLinksView,
    StatusOverviewView,
    StatusPageView,
    heartbeat_incidents,
    heartbeat_ping,
    maintenance_create,
    maintenance_delete,
    maintenance_edit,
    reset_epoch,
    status_json,
    verify_smallstack,
)

app_name = "heartbeat"

urlpatterns = [
    # CRUDView-generated routes for user-created endpoint monitors
    # (status/endpoints/, status/endpoints/create/, …).
    *MonitoredEndpointCRUDView.get_urls(),
    # CRUDView-generated routes for Site Monitors (picked exposed surfaces).
    *MonitoredSurfaceCRUDView.get_urls(),
    path("status/endpoints/verify/", verify_smallstack, name="verify_smallstack"),
    path("ping/", heartbeat_ping, name="ping"),
    path("status/", StatusPageView.as_view(), name="status"),
    path("status/overview/", StatusOverviewView.as_view(), name="status_overview"),
    path("status/dev-links/", StatusDevLinksView.as_view(), name="dev_links"),
    path("status/monitor/<slug:monitor_key>/", MonitorDetailView.as_view(), name="monitor_detail"),
    path("status/json/", status_json, name="status_json"),
    path("status/dashboard/", HeartbeatDashboardView.as_view(), name="dashboard"),
    path("status/dashboard/incidents/", heartbeat_incidents, name="incidents"),
    path("status/sla/", SLADetailView.as_view(), name="sla"),
    path("status/reset-epoch/", reset_epoch, name="reset_epoch"),
    path("status/sla/maintenance/add/", maintenance_create, name="maintenance_create"),
    path("status/sla/maintenance/<int:pk>/edit/", maintenance_edit, name="maintenance_edit"),
    path("status/sla/maintenance/<int:pk>/delete/", maintenance_delete, name="maintenance_delete"),
]
