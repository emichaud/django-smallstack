"""URL configuration for the heartbeat app."""

from django.urls import path

from .views import (
    HeartbeatDashboardView,
    SLADetailView,
    StatusPageView,
    heartbeat_ping,
    maintenance_create,
    maintenance_delete,
    maintenance_edit,
    reset_epoch,
    status_json,
)

app_name = "heartbeat"

urlpatterns = [
    path("ping/", heartbeat_ping, name="ping"),
    path("status/", StatusPageView.as_view(), name="status"),
    path("status/json/", status_json, name="status_json"),
    path("status/dashboard/", HeartbeatDashboardView.as_view(), name="dashboard"),
    path("status/sla/", SLADetailView.as_view(), name="sla"),
    path("status/reset-epoch/", reset_epoch, name="reset_epoch"),
    path("status/sla/maintenance/add/", maintenance_create, name="maintenance_create"),
    path("status/sla/maintenance/<int:pk>/edit/", maintenance_edit, name="maintenance_edit"),
    path("status/sla/maintenance/<int:pk>/delete/", maintenance_delete, name="maintenance_delete"),
]
