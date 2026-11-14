"""URL config for /smallstack/search/ + the omnibar JSON endpoint.

Mounted under apps/smallstack/site_urls.py at "search/".
"""

from django.urls import path

from .api import search_api
from .views import OmnibarSearchView, SearchDiagnosticsView, SearchPageView

app_name = "search"

urlpatterns = [
    path("", SearchPageView.as_view(), name="page"),
    path("omnibar/", OmnibarSearchView.as_view(), name="omnibar"),
    path("diagnostics/", SearchDiagnosticsView.as_view(), name="diagnostics"),
    path("api/", search_api, name="api"),
]
