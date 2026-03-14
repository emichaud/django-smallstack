"""
URL configuration for smallstack project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.heartbeat.views import StatusPageView, status_json

from .views import health_check, legal_page_view

urlpatterns = [
    # Project pages - customize these in apps/website/
    path("", include("apps.website.urls")),
    # All built-in SmallStack URLs (auth, profile, help, activity, heartbeat, backups, usermanager)
    path("smallstack/", include("apps.smallstack.site_urls")),
    # Public convenience aliases — downstream projects can change or remove these.
    # Status serves directly (public, no login); profile/help redirect to canonical URLs.
    path("status/", StatusPageView.as_view(), name="public_status"),
    path("status/json/", status_json, name="public_status_json"),
    path("profile/", RedirectView.as_view(pattern_name="profile", permanent=False), name="public_profile"),
    path("help/", RedirectView.as_view(pattern_name="help:index", permanent=False), name="public_help"),
    # Admin
    path("admin/", admin.site.urls),
    # Legal pages (public)
    path("privacy/", legal_page_view, {"page": "privacy-policy"}, name="privacy_policy"),
    path("terms/", legal_page_view, {"page": "terms-of-service"}, name="terms_of_service"),
    # Utility routes
    path("health/", health_check, name="health_check"),
    path(
        "robots.txt",
        RedirectView.as_view(url=f"{settings.STATIC_URL}robots.txt", permanent=True),
    ),
]

# Debug toolbar (development only)
if settings.DEBUG:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]

    # Preview error pages in development
    from django.views.defaults import bad_request, page_not_found, permission_denied, server_error

    urlpatterns += [
        path("_error/400/", bad_request, {"exception": Exception("preview")}),
        path("_error/403/", permission_denied, {"exception": Exception("preview")}),
        path("_error/404/", page_not_found, {"exception": Exception("preview")}),
        path("_error/500/", server_error),
    ]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # Serve media files in production via Django
    # Note: For high-traffic sites, use nginx or cloud storage (S3) instead
    from django.urls import re_path
    from django.views.static import serve

    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
