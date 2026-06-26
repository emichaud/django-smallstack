"""URL config for the Token Manager app.

Mounted at the root of /smallstack/ so every path resolves under
/smallstack/tokens/. CRUDView's get_urls() contributes the list
(/smallstack/tokens/) and detail (/smallstack/tokens/<pk>/) routes via
url_base="tokens". Custom paths for create/reveal/revoke/stats sit
beside them.
"""

from django.urls import path

from . import views

app_name = "tokenmgr"

urlpatterns = [
    # Custom routes (must match before CRUDView's tokens/<pk>/ pattern).
    path("tokens/create/", views.TokenCreateView.as_view(), name="token-create"),
    path("tokens/<int:pk>/reveal/", views.TokenRevealView.as_view(), name="token-reveal"),
    path("tokens/<int:pk>/revoke/", views.TokenRevokeView.as_view(), name="token-revoke"),
    path("tokens/<int:pk>/stats/", views.TokenStatsView.as_view(), name="token-stats"),
    # Overview stat-card drill-down modals on the list page.
    path("tokens/stats/<str:stat_type>/", views.token_stat_detail, name="token-stat-detail"),
    # CRUDView-generated list + detail (tokens/ and tokens/<pk>/).
    *views.TokenCRUDView.get_urls(),
]
