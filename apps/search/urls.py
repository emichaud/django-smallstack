"""URL config for /smallstack/search/ + the omnibar JSON endpoint.

Mounted under apps/smallstack/site_urls.py at "search/".
"""

from django.urls import path

from .views import OmnibarSearchView, SearchPageView

app_name = "search"

urlpatterns = [
    path("", SearchPageView.as_view(), name="page"),
    path("omnibar/", OmnibarSearchView.as_view(), name="omnibar"),
]
