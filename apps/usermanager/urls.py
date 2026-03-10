from django.urls import path

from .timezone_views import TimezoneDashboardView
from .views import UserCRUDView, user_stat_detail

urlpatterns = [
    path("manage/users/timezones/", TimezoneDashboardView.as_view(), name="manage/users-timezones"),
    path("manage/users/stats/<str:stat_type>/", user_stat_detail, name="manage/users-stat-detail"),
    *UserCRUDView.get_urls(),
]
