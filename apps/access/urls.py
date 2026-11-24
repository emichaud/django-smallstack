from django.urls import path

from . import views

app_name = "access"

urlpatterns = [
    path("", views.IndexView.as_view(), name="index"),
    path("findings/<slug:key>/", views.finding_detail, name="finding"),
    path("stats/<slug:stat>/", views.stat_detail, name="stat"),
    path("groups/", views.GroupsView.as_view(), name="groups"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/", views.GroupDetailView.as_view(), name="group_detail"),
    path("groups/<int:pk>/members/", views.group_members, name="group_members"),
    path("groups/<int:pk>/permissions/", views.group_permissions, name="group_permissions"),
    path("groups/<int:pk>/settings/", views.group_settings, name="group_settings"),
    path("groups/<int:pk>/directory/", views.group_directory, name="group_directory"),
    path("users/", views.UsersView.as_view(), name="users"),
    path("users/<int:pk>/", views.UserDetailView.as_view(), name="user_detail"),
    path("users/<int:pk>/groups/", views.user_groups, name="user_groups"),
    path("users/<int:pk>/permissions/", views.user_permissions, name="user_permissions"),
    path("users/<int:pk>/revoke/", views.user_revoke, name="user_revoke"),
    path("events/", views.EventsView.as_view(), name="events"),
    path("events.csv", views.events_csv, name="events_csv"),
    path("export/access.csv", views.matrix_csv, name="matrix_csv"),
    path("export/access.json", views.snapshot_json, name="snapshot_json"),
    path("reviews/", views.ReviewsView.as_view(), name="reviews"),
    path("reviews/open/", views.review_open, name="review_open"),
    path("reviews/<int:pk>/", views.ReviewDetailView.as_view(), name="review_detail"),
    path("reviews/<int:pk>/decide/", views.review_decide, name="review_decide"),
    path("reviews/<int:pk>/sign/", views.review_sign, name="review_sign"),
    path("reviews/<int:pk>/print/", views.ReviewPrintView.as_view(), name="review_print"),
    path("reviews/<int:pk>.csv", views.review_csv, name="review_csv"),
    path("reviews/<int:pk>.json", views.review_json, name="review_json"),
    path("evidence/", views.EvidenceView.as_view(), name="evidence"),
    path("evidence/print/", views.EvidencePrintView.as_view(), name="evidence_print"),
    path("evidence/<slug:key>.csv", views.evidence_sheet_csv, name="evidence_csv"),
    path("evidence.json", views.evidence_json, name="evidence_json"),
    path("evidence.zip", views.evidence_zip, name="evidence_zip"),
    path("evidence/packs/store/", views.evidence_store, name="evidence_store"),
    path("evidence/packs/<int:pk>.zip", views.evidence_pack, name="evidence_pack"),
]
