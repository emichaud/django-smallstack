"""
URL configuration for the help app.

Supports hierarchical documentation with sections (folders).
"""

from django.urls import path

from .views import (
    HelpDetailView,
    HelpIndexView,
    HelpSectionDetailView,
    HelpSectionIndexView,
    HelpSectionTocView,
    SlideView,
    help_bubble,
    help_page_markdown,
    search_index_view,
)

app_name = "help"

urlpatterns = [
    path("", HelpIndexView.as_view(), name="index"),
    path("search-index.json", search_index_view, name="search_index"),
    path("slides/<slug:deck_slug>/", SlideView.as_view(), name="slides"),
    # Section table of contents (e.g., /smallstack/help/smallstack/toc/)
    # Markdown alternates (llms.txt convention): the page with .md appended.
    path("<slug:section>/<slug:slug>.md", help_page_markdown, name="section_detail_md"),
    path("<slug:slug>.md", help_page_markdown, name="detail_md"),
    path("<slug:section>/toc/", HelpSectionTocView.as_view(), name="section_toc"),
    # A page as a modal fragment, for {% help_bubble %} (e.g., /smallstack/help/dashboards/component/bubble/)
    path("<slug:section>/<slug:slug>/bubble/", help_bubble, name="section_bubble"),
    path("<slug:slug>/bubble/", help_bubble, name="bubble"),
    # Section pages (e.g., /smallstack/help/smallstack/getting-started/)
    path("<slug:section>/<slug:slug>/", HelpSectionDetailView.as_view(), name="section_detail"),
    # Section index (e.g., /smallstack/help/smallstack/) - must come after section_detail
    path("<slug:section>/", HelpSectionIndexView.as_view(), name="section_index"),
    # Root pages (e.g., /smallstack/help/index/)
    path("<slug:slug>/", HelpDetailView.as_view(), name="detail"),
]
