"""URL configuration for the activity app."""

from django.urls import path

from .views import (
    ActivityDashboardView,
    ActivityStatDetailView,
    RequestListView,
    ResourceDetailView,
    ResourceListView,
    UserActivityView,
    UserDetailView,
)

app_name = "activity"

urlpatterns = [
    path("", ActivityDashboardView.as_view(), name="dashboard"),
    path("stat/<str:stat>/", ActivityStatDetailView.as_view(), name="stat_detail"),
    path("requests/", RequestListView.as_view(), name="requests"),
    path("users/", UserActivityView.as_view(), name="users"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user_detail"),
    path("resources/", ResourceListView.as_view(), name="resources"),
    # Resource keys contain slashes and "<int:pk>" segments, so the key travels
    # as ?r= rather than in the path.
    path("resources/detail/", ResourceDetailView.as_view(), name="resource_detail"),
]
