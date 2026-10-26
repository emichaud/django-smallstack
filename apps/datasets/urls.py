"""URL routes for the datasets REST surface + staff browser (mounted at /smallstack/datasets/)."""

from __future__ import annotations

from django.urls import path

from .api import (
    DatasetListView,
    DatasetRowsView,
    DatasetScalarView,
    DatasetSchemaView,
    DatasetSeriesView,
)
from .views import DatasetBrowseView, DatasetIndexView

app_name = "datasets"

urlpatterns = [
    path("", DatasetListView.as_view(), name="list"),
    # The staff browser (HTML) — before the catch-all <key>/ rows route.
    path("browse/", DatasetIndexView.as_view(), name="browse-index"),
    path("browse/<str:key>/", DatasetBrowseView.as_view(), name="browse"),
    # Specific sub-routes before the catch-all <key>/ rows route.
    path("<str:key>/schema/", DatasetSchemaView.as_view(), name="schema"),
    path("<str:key>/series/", DatasetSeriesView.as_view(), name="series"),
    path("<str:key>/scalar/", DatasetScalarView.as_view(), name="scalar"),
    path("<str:key>/", DatasetRowsView.as_view(), name="rows"),
]
