"""
All built-in SmallStack URLs, aggregated in one place.

Include in config/urls.py with: path("", include("apps.smallstack.site_urls"))

A downstream project can wrap with a prefix if desired:
    path("tools/", include("apps.smallstack.site_urls"))
"""

from django.urls import include, path

from apps.accounts.views import SignupView
from apps.smallstack.views import SmallStackDashboardView

urlpatterns = [
    # Dashboard (staff-only landing page)
    path("", SmallStackDashboardView.as_view(), name="smallstack_dashboard"),
    # Authentication
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/signup/", SignupView.as_view(), name="signup"),
    # Profile
    path("profile/", include("apps.profile.urls")),
    # Help/Documentation
    path("help/", include("apps.help.urls")),
    # Activity tracking
    path("activity/", include("apps.activity.urls")),
    # Heartbeat / Status
    path("", include("apps.heartbeat.urls")),
    # Backups (staff-only)
    path("backups/", include("apps.smallstack.urls")),
    # User Manager (staff-only)
    path("", include("apps.usermanager.urls")),
    # Model Explorer (staff-only)
    path("", include("apps.explorer.urls")),
]
