"""
URL configuration for smallstack project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from .views import health_check, legal_page_view, starter_basic_view, starter_forms_view, starter_view

urlpatterns = [
    # Project pages - customize these in apps/website/
    path("", include("apps.website.urls")),
    # All built-in SmallStack URLs (auth, profile, help, activity, heartbeat, backups, usermanager)
    path("", include("apps.smallstack.site_urls")),
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
    # Starter/Example page - demonstrates available components
    path("starter/", starter_view, name="starter"),
    path("starter/basic/", starter_basic_view, name="starter_basic"),
    path("starter/forms/", starter_forms_view, name="starter_forms"),
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
