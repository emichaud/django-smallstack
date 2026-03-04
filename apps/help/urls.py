"""
URL configuration for the help app.

Supports hierarchical documentation with sections (folders).
"""

from django.urls import path

from .views import HelpDetailView, HelpIndexView, HelpSectionDetailView, HelpSectionIndexView, search_index_view

app_name = "help"

urlpatterns = [
    path("", HelpIndexView.as_view(), name="index"),
    path("search-index.json", search_index_view, name="search_index"),
    # Section pages (e.g., /help/smallstack/getting-started/)
    path("<slug:section>/<slug:slug>/", HelpSectionDetailView.as_view(), name="section_detail"),
    # Section index (e.g., /help/smallstack/) - must come after section_detail
    path("<slug:section>/", HelpSectionIndexView.as_view(), name="section_index"),
    # Root pages (e.g., /help/index/)
    path("<slug:slug>/", HelpDetailView.as_view(), name="detail"),
]
