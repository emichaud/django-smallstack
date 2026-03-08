"""URL configuration for SmallStack backup views."""

from django.urls import path

from . import views

app_name = "smallstack"

urlpatterns = [
    path("", views.BackupPageView.as_view(), name="backups"),
    path("<int:pk>/", views.BackupDetailView.as_view(), name="backup_detail"),
    path("stat/<str:stat>/", views.BackupStatDetailView.as_view(), name="backup_stat_detail"),
    path("now/", views.BackupNowView.as_view(), name="backup_now"),
    path("download/", views.BackupDownloadView.as_view(), name="backup_download"),
    path("download/<str:filename>/", views.BackupFileDownloadView.as_view(), name="backup_file_download"),
]
