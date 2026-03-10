"""URL configuration for the heartbeat app."""

from django.urls import path

from .views import HeartbeatDashboardView, SLADetailView, StatusPageView, reset_epoch, status_json

app_name = "heartbeat"

urlpatterns = [
    path("status/", StatusPageView.as_view(), name="status"),
    path("status/json/", status_json, name="status_json"),
    path("status/dashboard/", HeartbeatDashboardView.as_view(), name="dashboard"),
    path("status/sla/", SLADetailView.as_view(), name="sla"),
    path("status/reset-epoch/", reset_epoch, name="reset_epoch"),
]
