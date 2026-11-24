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
    path(
        "api/access/users/<str:user>/permissions/<str:perm>/",
        api.api_user_permission,
        name="access-api-user-permission",
    ),
    path("api/access/groups/", api.api_groups, name="access-api-groups"),
    path("api/access/groups/<str:group>/", api.api_group, name="access-api-group"),
    path(
        "api/access/groups/<str:group>/permissions/<str:perm>/",
        api.api_group_permission,
        name="access-api-group-permission",
    ),
    path("api/access/findings/", api.api_findings, name="access-api-findings"),
    path("api/access/events/", api.api_events, name="access-api-events"),
    path("api/access/reviews/", api.api_reviews, name="access-api-reviews"),
    path("api/access/reviews/<int:review_id>/", api.api_review, name="access-api-review"),
    path("api/access/evidence/", api.api_evidence, name="access-api-evidence"),
    path("api/access/evidence/packs/", api.api_evidence_packs, name="access-api-evidence-packs"),
    path("api/access/evidence/packs/<int:pack_id>/", api.api_evidence_pack, name="access-api-evidence-pack"),
    path("api/access/reviews/cadence/", api.api_review_cadence, name="access-api-review-cadence"),
]
