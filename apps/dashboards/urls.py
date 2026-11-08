"""Dashboards URLs, mounted under ``/smallstack/`` by apps/smallstack/site_urls.py.

No ``app_name``: this module hosts CRUDViews, whose internal reverses use bare
route names (the calendar / blog / scheduler precedent). Pages are named
``dashboards_*``; the CRUD routes are ``dashboards/metrics-*``,
``dashboards/boards-*``, ``dashboards/reports-*``, ``dashboards/playlists-*``,
``dashboards/components-*`` and ``dashboards/goals-*``.
"""

from __future__ import annotations

from django.urls import path

from . import api, views

urlpatterns = [
    path("dashboards/", views.DashboardIndexView.as_view(), name="dashboards_index"),
    path("goals/", views.GoalsIndexView.as_view(), name="goals_index"),
    path("dashboards/mine/", views.MyDashboardsView.as_view(), name="dashboards_mine"),
    path("dashboards/d/<slug:slug>/", views.DashboardPageView.as_view(), name="dashboards_dashboard"),
    path(
        "dashboards/d/<slug:slug>/cells/<str:cell_id>/",
        views.DashboardCellView.as_view(),
        name="dashboards_cell",
    ),
    path("dashboards/d/<slug:slug>/layout/", views.DashboardLayoutView.as_view(), name="dashboards_layout"),
    path("dashboards/d/<slug:slug>/digest/", views.DashboardDigestView.as_view(), name="dashboards_digest"),
    path("dashboards/d/<slug:slug>/cards/", views.DashboardCardsView.as_view(), name="dashboards_board_cards"),
    path(
        "dashboards/d/<slug:slug>/cards/<str:cell_id>/edit/",
        views.DashboardCardEditView.as_view(),
        name="dashboards_card_edit",
    ),
    path(
        "dashboards/d/<slug:slug>/cards/<str:cell_id>/copy/",
        views.DashboardCardCopyView.as_view(),
        name="dashboards_card_copy",
    ),
    path(
        "dashboards/d/<slug:slug>/cards/<str:cell_id>/rows/",
        views.CellRowsView.as_view(),
        name="dashboards_cell_rows",
    ),
    path("dashboards/d/<slug:slug>/share/", views.DashboardShareView.as_view(), name="dashboards_share"),
    path(
        "dashboards/d/<slug:slug>/cards/<str:cell_id>/value/",
        views.DashboardCardValueView.as_view(),
        name="dashboards_board_card_value",
    ),
    path(
        "dashboards/card-preview/<int:pk>/",
        views.ComponentPreviewView.as_view(),
        name="dashboards_component_preview",
    ),
    path("dashboards/m/<slug:key>/", views.MetricDetailView.as_view(), name="dashboards_metric_detail"),
    path("dashboards/m/<slug:key>/rows/", views.MetricRowsView.as_view(), name="dashboards_metric_rows"),
    path("dashboards/m/<slug:key>/entries/", views.MetricEntrySaveView.as_view(), name="dashboards_metric_entry_save"),
    path(
        "dashboards/m/<slug:key>/entries/<str:day>/delete/",
        views.MetricEntryDeleteView.as_view(),
        name="dashboards_metric_entry_delete",
    ),
    path("dashboards/preview-rows/", views.MetricPreviewRowsView.as_view(), name="dashboards_preview_rows"),
    path("dashboards/metrics/quick/", views.MetricQuickView.as_view(), name="dashboards_metric_quick"),
    path("dashboards/archive/<str:kind>/<int:pk>/", views.ArchiveToggleView.as_view(), name="dashboards_archive"),
    path(
        "dashboards/duplicate/<str:kind>/<int:pk>/", views.DuplicateConfirmView.as_view(), name="dashboards_duplicate"
    ),
    path(
        "dashboards/defaults/reset/<str:kind>/<int:pk>/",
        views.DefaultResetView.as_view(),
        name="dashboards_default_reset",
    ),
    path("dashboards/r/<slug:slug>/", views.ReportPageView.as_view(), name="dashboards_report"),
    path("dashboards/p/<slug:slug>/", views.PlaylistPlayerView.as_view(), name="dashboards_playlist"),
    path(
        "dashboards/p/<slug:slug>/slides/<int:position>/",
        views.PlaylistSlideView.as_view(),
        name="dashboards_playlist_slide",
    ),
    path("dashboards/r/<slug:slug>/print/", views.ReportPrintView.as_view(), name="dashboards_report_print"),
    path("dashboards/r/<slug:slug>/digest/", views.ReportDigestView.as_view(), name="dashboards_report_digest"),
    path("dashboards/g/<slug:slug>/", views.GoalListPageView.as_view(), name="dashboards_goals"),
    path("dashboards/g/<slug:slug>/digest/", views.GoalListDigestView.as_view(), name="dashboards_goals_digest"),
    path("dashboards/g/<slug:slug>/print/", views.GoalListPrintView.as_view(), name="dashboards_goals_print"),
    path("dashboards/g/<slug:slug>/history/", views.GoalHistoryView.as_view(), name="dashboards_goal_history"),
    path(
        "dashboards/g/<slug:slug>/history/tracking/",
        views.GoalTrackingView.as_view(),
        name="dashboards_goal_tracking",
    ),
    path("dashboards/g/<slug:slug>/history/capture/", views.GoalCaptureView.as_view(), name="dashboards_goal_capture"),
    path("dashboards/g/<slug:slug>/weeks/", views.GoalWeeksView.as_view(), name="dashboards_goal_weeks"),
    path(
        "dashboards/g/<slug:slug>/weeks/<str:week>/trends/",
        views.GoalWeekTrendsView.as_view(),
        name="dashboards_goal_week_trends",
    ),
    path(
        "dashboards/g/<slug:slug>/goals/<str:goal_id>/trends/",
        views.GoalWeeksTrendView.as_view(),
        name="dashboards_goal_weeks_trend",
    ),
    path(
        "dashboards/g/<slug:slug>/weeks/<str:week>/snapshot/",
        views.GoalWeekSnapshotView.as_view(),
        name="dashboards_goal_week_snapshot",
    ),
    path("dashboards/goals/add/", views.AddGoalView.as_view(), name="dashboards_goal_add"),
    # JSON for builders + agents (Bearer or session)
    path("dashboards/api/components/", api.ComponentsApiView.as_view(), name="dashboards_api_components"),
    path("dashboards/api/datasets/", api.DatasetsApiView.as_view(), name="dashboards_api_datasets"),
    path(
        "dashboards/api/datasets/<str:key>/schema/",
        api.DatasetSchemaApiView.as_view(),
        name="dashboards_api_dataset_schema",
    ),
    path("dashboards/api/preview/", api.PreviewApiView.as_view(), name="dashboards_api_preview"),
    path("dashboards/api/report-preview/", api.ReportPreviewApiView.as_view(), name="dashboards_api_report_preview"),
    path("dashboards/api/card-preview/", api.CardPreviewApiView.as_view(), name="dashboards_api_card_preview"),
    path("dashboards/api/preview-rows/", api.PreviewRowsApiView.as_view(), name="dashboards_api_preview_rows"),
    path(
        "dashboards/api/metrics/<slug:key>/value/",
        api.MetricValueApiView.as_view(),
        name="dashboards_api_metric_value",
    ),
    path(
        "dashboards/api/metrics/<slug:key>/entries/",
        api.MetricEntriesApiView.as_view(),
        name="dashboards_api_metric_entries",
    ),
    path(
        "dashboards/api/metrics/<slug:key>/trend/",
        api.MetricTrendApiView.as_view(),
        name="dashboards_api_metric_trend",
    ),
    path(
        "dashboards/api/metrics/<slug:key>/rows/",
        api.MetricRowsApiView.as_view(),
        name="dashboards_api_metric_rows",
    ),
    path(
        "dashboards/api/boards/<slug:slug>/values/",
        api.BoardValuesApiView.as_view(),
        name="dashboards_api_board_values",
    ),
    path(
        "dashboards/api/boards/<slug:slug>/picture/",
        api.BoardPictureApiView.as_view(),
        name="dashboards_api_board_picture",
    ),
    path(
        "dashboards/api/playlists/<slug:slug>/slides/",
        api.PlaylistSlidesApiView.as_view(),
        name="dashboards_api_playlist_slides",
    ),
    path(
        "dashboards/api/goals/<slug:slug>/values/",
        api.GoalValuesApiView.as_view(),
        name="dashboards_api_goal_values",
    ),
    path(
        "dashboards/api/goals/<slug:slug>/snapshots/",
        api.GoalSnapshotsApiView.as_view(),
        name="dashboards_api_goal_snapshots",
    ),
    path(
        "dashboards/api/goals/<slug:slug>/tracking/",
        api.GoalTrackingApiView.as_view(),
        name="dashboards_api_goal_tracking",
    ),
    path(
        "dashboards/api/goals/<slug:slug>/weeks/",
        api.GoalWeeksApiView.as_view(),
        name="dashboards_api_goal_weeks",
    ),
    path(
        "dashboards/api/goals/<slug:slug>/weeks/<str:week>/save/",
        api.GoalWeekSaveApiView.as_view(),
        name="dashboards_api_goal_week_save",
    ),
    path(
        "dashboards/api/reports/<slug:slug>/values/",
        api.ReportValuesApiView.as_view(),
        name="dashboards_api_report_values",
    ),
    *views.MetricCRUDView.get_urls(),
    *views.DashboardCRUDView.get_urls(),
    *views.ReportCRUDView.get_urls(),
    *views.PlaylistCRUDView.get_urls(),
    *views.ComponentCRUDView.get_urls(),
    *views.GoalListCRUDView.get_urls(),
]
