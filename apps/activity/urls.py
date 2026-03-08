"""URL configuration for the activity app."""

from django.urls import path

from .views import ActivityDashboardView, ActivityStatDetailView, RequestListView, UserActivityView

app_name = "activity"

urlpatterns = [
    path("", ActivityDashboardView.as_view(), name="dashboard"),
    path("stat/<str:stat>/", ActivityStatDetailView.as_view(), name="stat_detail"),
    path("requests/", RequestListView.as_view(), name="requests"),
    path("users/", UserActivityView.as_view(), name="users"),
]
