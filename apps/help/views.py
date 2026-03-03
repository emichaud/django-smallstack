"""
Views for the help/documentation app.

Supports hierarchical documentation with sections (folders).
"""

from django.http import Http404, JsonResponse
from django.views.generic import TemplateView

from .utils import build_search_index, get_all_sections, get_config, get_help_page, get_section_pages


class HelpIndexView(TemplateView):
    """Display the help documentation index with sections."""

    template_name = "help/help_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = get_config()
        context["sections"] = get_all_sections()
        context["page_title"] = config.get("title", "Help & Documentation")
        context["config"] = config
        return context


class HelpDetailView(TemplateView):
    """Display a root-level help page."""

    template_name = "help/help_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs.get("slug")

        page = get_help_page(slug, section="")
        if page is None:
            raise Http404("Help page not found")

        context["page"] = page
        context["sections"] = get_all_sections()
        context["current_section"] = ""
        context["section_pages"] = get_section_pages("")
        context["page_title"] = page["title"]

        # Find prev/next pages for navigation within section
        pages = context["section_pages"]
        current_idx = next(
            (i for i, p in enumerate(pages) if p["slug"] == slug),
            None,
        )
        if current_idx is not None:
            context["prev_page"] = pages[current_idx - 1] if current_idx > 0 else None
            context["next_page"] = pages[current_idx + 1] if current_idx < len(pages) - 1 else None

        return context


class HelpSectionDetailView(TemplateView):
    """Display a help page within a section."""

    template_name = "help/help_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        section = self.kwargs.get("section")
        slug = self.kwargs.get("slug")

        page = get_help_page(slug, section=section)
        if page is None:
            raise Http404("Help page not found")

        context["page"] = page
        context["sections"] = get_all_sections()
        context["current_section"] = section
        context["section_pages"] = get_section_pages(section)
        context["page_title"] = page["title"]

        # Find prev/next pages for navigation within section
        pages = context["section_pages"]
        current_idx = next(
            (i for i, p in enumerate(pages) if p["slug"] == slug),
            None,
        )
        if current_idx is not None:
            context["prev_page"] = pages[current_idx - 1] if current_idx > 0 else None
            context["next_page"] = pages[current_idx + 1] if current_idx < len(pages) - 1 else None

        return context


def search_index_view(request):
    """Return JSON search index for client-side search."""
    index = build_search_index()
    return JsonResponse({"pages": index})
