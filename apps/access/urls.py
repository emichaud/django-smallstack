from django.urls import path

from . import views

app_name = "access"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("findings/<slug:key>/", views.finding_detail, name="finding"),
    path("stats/<slug:stat>/", views.stat_detail, name="stat"),
    path("groups/", views.GroupsView.as_view(), name="groups"),
    path("groups/<int:pk>/", views.GroupDetailView.as_view(), name="group_detail"),
    path("groups/<int:pk>/members/", views.group_members, name="group_members"),
    path("users/", views.UsersView.as_view(), name="users"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/groups/", views.user_groups, name="user_groups"),
    path("users/<int:pk>/revoke/", views.user_revoke, name="user_revoke"),
    path("events/", views.EventsView.as_view(), name="events"),
    path("events.csv", views.events_csv, name="events_csv"),
    path("export/access.csv", views.matrix_csv, name="matrix_csv"),
    path("export/access.json", views.snapshot_json, name="snapshot_json"),
]
