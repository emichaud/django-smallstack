"""URL configuration for SmallStack backup views."""

from django.urls import path

from . import views

app_name = "smallstack"

urlpatterns = [
    path("", views.BackupPageView.as_view(), name="backups"),
    path("download/", views.BackupDownloadView.as_view(), name="backup_download"),
    path("download/<str:filename>/", views.BackupFileDownloadView.as_view(), name="backup_file_download"),
]
