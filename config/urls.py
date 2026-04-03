"""
URL configuration for smallstack project.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.heartbeat.views import StatusPageView, status_json
from apps.smallstack.api import (
    api_auth_logout,
    api_auth_me,
    api_auth_password,
    api_auth_password_requirements,
    api_auth_register,
    api_auth_token,
    api_auth_token_refresh,
    api_auth_user_deactivate,
    api_auth_user_detail,
    api_auth_user_password,
    api_auth_users,
    api_openapi_schema,
    api_schema,
)

from .views import health_check, legal_page_view

urlpatterns = [
    # Project pages - customize these in apps/website/
    path("", include("apps.website.urls")),
    # All built-in SmallStack URLs (auth, profile, help, activity, heartbeat, backups, usermanager)
    path("smallstack/", include("apps.smallstack.site_urls")),
    # Public convenience aliases — downstream projects can change or remove these.
    # Auth aliases let /accounts/login/ work alongside the canonical /smallstack/accounts/login/.
    # Status serves directly (public, no login); others redirect to canonical URLs.
    path("accounts/login/", RedirectView.as_view(pattern_name="login", permanent=False), name="public_login"),
    path("accounts/logout/", RedirectView.as_view(pattern_name="logout", permanent=False), name="public_logout"),
    path("accounts/signup/", RedirectView.as_view(pattern_name="signup", permanent=False), name="public_signup"),
    path("status/", StatusPageView.as_view(), name="public_status"),
    path("status/json/", status_json, name="public_status_json"),
    path("profile/", include("apps.profile.urls")),
    path("help/", RedirectView.as_view(pattern_name="help:index", permanent=False), name="public_help"),
    # API schema (no auth required)
    path("api/schema/", api_schema, name="api-schema"),
    path("api/schema/openapi.json", api_openapi_schema, name="api-openapi-schema"),
    # API auth
    path("api/auth/token/", api_auth_token, name="api-auth-token"),
    path("api/auth/token/refresh/", api_auth_token_refresh, name="api-auth-token-refresh"),
    path("api/auth/register/", api_auth_register, name="api-auth-register"),
    path("api/auth/me/", api_auth_me, name="api-auth-me"),
    path("api/auth/password/", api_auth_password, name="api-auth-password"),
    path("api/auth/password-requirements/", api_auth_password_requirements, name="api-auth-password-requirements"),
    path("api/auth/users/<int:user_id>/password/", api_auth_user_password, name="api-auth-user-password"),
    path("api/auth/users/<int:user_id>/deactivate/", api_auth_user_deactivate, name="api-auth-user-deactivate"),
    path("api/auth/users/", api_auth_users, name="api-auth-users"),
    path("api/auth/users/<int:user_id>/", api_auth_user_detail, name="api-auth-user-detail"),
    path("api/auth/logout/", api_auth_logout, name="api-auth-logout"),
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
