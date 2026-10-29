"""Calendar URLs, mounted under ``/smallstack/`` by apps/smallstack/site_urls.py.

No ``app_name``: this module hosts a CRUDView, whose internal reverses use
bare route names (the blog / scheduler / webhooks precedent). The page and API
routes are named ``calendar_*``; the saved-view CRUD is ``calendar/views-*``.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

urlpatterns = [
    path("calendar/", views.CalendarPageView.as_view(), name="calendar_index"),
    path("calendar/api/", api.CalendarListView.as_view(), name="calendar_api_list"),
    path("calendar/api/events/", api.CalendarEventsView.as_view(), name="calendar_api_events"),
    path("calendar/api/events.ics", api.CalendarICSView.as_view(), name="calendar_api_ics"),
    path("calendar/api/<str:key>/events/", api.CalendarDatasetEventsView.as_view(), name="calendar_api_dataset_events"),
    *views.SavedCalendarViewCRUDView.get_urls(),
]
