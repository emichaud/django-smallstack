"""Calendar URLs, mounted under ``/smallstack/`` by apps/smallstack/site_urls.py.

No ``app_name``: this module hosts a CRUDView, whose internal reverses use
bare route names (the blog / scheduler / webhooks precedent). The page and API
routes are named ``calendar_*``; the saved-view CRUD is ``calendar/views-*`` and
the Events calendar's CRUD is ``calendar/events-*``.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

urlpatterns = [
    path("calendar/", views.CalendarPageView.as_view(), name="calendar_index"),
    # The embed fragment — what {% calendar_card %} and the calendar dashboard card load.
    path("calendar/embed/", views.CalendarEmbedView.as_view(), name="calendar_embed"),
    path("calendar/api/", api.CalendarListView.as_view(), name="calendar_api_list"),
    path("calendar/api/events/", api.CalendarEventsView.as_view(), name="calendar_api_events"),
    path("calendar/api/events.ics", api.CalendarICSView.as_view(), name="calendar_api_ics"),
    path("calendar/api/<str:key>/events/", api.CalendarDatasetEventsView.as_view(), name="calendar_api_dataset_events"),
    path("calendar/events/<int:pk>/skip/", views.EventSkipView.as_view(), name="calendar_event_skip"),
    *views.SavedCalendarViewCRUDView.get_urls(),
    *views.EventCRUDView.get_urls(),
]
