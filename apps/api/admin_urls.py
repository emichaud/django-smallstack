"""URL config for the API admin web pages.

Mounted at ``/smallstack/api/`` via apps/smallstack/site_urls.py. The
runtime REST surface stays at ``/api/`` (config/urls.py); these admin
pages observe it from a staff-gated path.
"""

from django.urls import path

from .admin_views import APIAdminActivityView, APIAdminHealthView, APIAdminSelfTestView

app_name = "api_admin"

urlpatterns = [
    path("", APIAdminHealthView.as_view(), name="health"),
    path("health/", APIAdminHealthView.as_view(), name="health_alias"),
    path("activity/", APIAdminActivityView.as_view(), name="activity"),
    # POST-only — backs the "Run Self-Test" button on Health.
    path("self-test/", APIAdminSelfTestView.as_view(), name="self_test"),
]
