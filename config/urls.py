"""
URL configuration for smallstack project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.views import SignupView

from .views import health_check, legal_page_view, starter_basic_view, starter_forms_view, starter_view

urlpatterns = [
    # Project pages - customize these in apps/website/
    path("", include("apps.website.urls")),
    # User Manager (staff-only)
    path("", include("apps.usermanager.urls")),
    # Admin
    path("admin/", admin.site.urls),
    # Authentication
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/signup/", SignupView.as_view(), name="signup"),
    # Profile
    path("profile/", include("apps.profile.urls")),
    # Help/Documentation
    path("help/", include("apps.help.urls")),
    # Activity tracking
    path("activity/", include("apps.activity.urls")),
    # Backups (staff-only)
    path("backups/", include("apps.smallstack.urls")),
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
