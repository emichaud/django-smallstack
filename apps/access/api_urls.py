"""REST routes, mounted at the site root so they sit at /smallstack/api/access/
beside the approvals ones. Unnamespaced: ``register_api_path`` anchors the
schema on the param-free names."""

from django.urls import path

from . import api

urlpatterns = [
    path("api/access/users/", api.api_users, name="access-api-users"),
    path("api/access/users/<str:user>/", api.api_user, name="access-api-user"),
    path("api/access/users/<str:user>/check/", api.api_user_check, name="access-api-user-check"),
    path("api/access/users/<str:user>/groups/<str:group>/", api.api_user_group, name="access-api-user-group"),
    path("api/access/groups/", api.api_groups, name="access-api-groups"),
    path("api/access/groups/<str:group>/", api.api_group, name="access-api-group"),
    path("api/access/findings/", api.api_findings, name="access-api-findings"),
    path("api/access/events/", api.api_events, name="access-api-events"),
]
