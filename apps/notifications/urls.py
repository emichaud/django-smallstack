"""Notification URLs.

`app_name` is safe here — this app has no CRUDViews (the bare-names footgun
only applies to apps hosting CRUDView routes). Telemetry precedent.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

app_name = "notifications"

urlpatterns = [
    path("", views.InboxView.as_view(), name="inbox"),
    path("<int:pk>/open/", views.open_notification, name="open"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
    # REST (Bearer or session) — the machine-readable inbox
    path("api/", api.api_list_notifications, name="api_list"),
    path("api/mark-read/", api.api_mark_read, name="api_mark_read"),
]
