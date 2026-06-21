"""
All built-in SmallStack URLs, aggregated in one place.

Include in config/urls.py with: path("", include("apps.smallstack.site_urls"))

A downstream project can wrap with a prefix if desired:
    path("tools/", include("apps.smallstack.site_urls"))
"""

from django.conf import settings
from django.contrib.auth.views import PasswordResetView
from django.urls import include, path

from apps.accounts.views import SignupView
from apps.smallstack.views import LayoutPreviewView, NavGuideView, SmallStackDashboardView

urlpatterns = [
    # Dashboard (staff-only landing page)
    path("", SmallStackDashboardView.as_view(), name="smallstack_dashboard"),
    # Layout preview (staff-only)
    path("layouts/", LayoutPreviewView.as_view(), name="layout_preview"),
    # Navigation guide (staff-only)
    path("nav-guide/", NavGuideView.as_view(), name="nav_guide"),
    # Authentication. Override password_reset BEFORE the stock auth-urls
    # include so reset emails get the branded HTML alternative and the real
    # SITE_NAME (otherwise django.contrib.auth sends plain-text only and signs
    # off with the raw request host, since contrib.sites isn't installed).
    # (Audit L4/L5.)
    path(
        "accounts/password_reset/",
        PasswordResetView.as_view(
            html_email_template_name="registration/password_reset_email_html.html",
            extra_email_context={"site_name": getattr(settings, "SITE_NAME", "SmallStack")},
        ),
        name="password_reset",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/signup/", SignupView.as_view(), name="signup"),
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
    # MCP admin pages (staff-only) — Health, Tools, Activity
    path("mcp/", include("apps.mcp.admin_urls")),
    # API admin pages (staff-only) — Health, Activity + threat panel
    path("api/", include("apps.api.admin_urls")),
    # Search — global keyword search page + omnibar JSON endpoint
    path("search/", include("apps.search.urls")),
    # Token manager (self-service + staff) — list, mint, reveal, revoke
    path("", include("apps.tokenmgr.urls")),
]
