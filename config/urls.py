"""
URL configuration for admin_starter project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts.views import SignupView

from .views import health_check, home_view, starter_view

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    # Authentication
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/signup/", SignupView.as_view(), name="signup"),
    # Profile
    path("profile/", include("apps.profile.urls")),
    # Help/Documentation
    path("help/", include("apps.help.urls")),
    # Utility routes
    path("health/", health_check, name="health_check"),
    path(
        "robots.txt",
        RedirectView.as_view(url=f"{settings.STATIC_URL}robots.txt", permanent=True),
    ),
    # Starter/Example page - demonstrates available components
    path("starter/", starter_view, name="starter"),
    # Home
    path("", home_view, name="home"),
]

# Debug toolbar (development only)
if settings.DEBUG:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]

# Serve media files
# Note: For high-traffic production, use nginx or cloud storage (S3) instead
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
