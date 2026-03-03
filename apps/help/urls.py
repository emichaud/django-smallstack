"""
URL configuration for the help app.
"""

from django.urls import path

from .views import HelpDetailView, HelpIndexView, search_index_view

app_name = "help"

urlpatterns = [
    path("", HelpIndexView.as_view(), name="index"),
    path("search-index.json", search_index_view, name="search_index"),
    path("<slug:slug>/", HelpDetailView.as_view(), name="detail"),
]
