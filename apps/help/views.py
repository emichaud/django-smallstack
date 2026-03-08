"""
Views for the help/documentation app.

Supports hierarchical documentation with sections (folders).
"""

from django.http import Http404, JsonResponse
from django.views.generic import TemplateView

from .utils import (
    SMALLSTACK_SECTION_SLUG,
    build_search_index,
    get_all_sections,
    get_config,
    get_deck_slides,
    get_help_page,
    get_section_pages,
    get_slide_deck,
)


class HelpIndexView(TemplateView):
    """Display the help documentation index with sections."""

    template_name = "help/help_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = get_config()
        # Exclude SmallStack section — it has its own sidebar link and index page
        context["sections"] = [s for s in get_all_sections() if s["slug"] != SMALLSTACK_SECTION_SLUG]
        context["page_title"] = config.get("title", "Help & Documentation")
        context["config"] = config
        return context


class HelpSectionIndexView(TemplateView):
    """Display the index page for a specific section with cards.

    Falls back to HelpDetailView if the slug is a root page, not a section.
    """

    template_name = "help/help_section_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        section_slug = self.kwargs.get("section")

        # Get all sections and find the requested one
        all_sections = get_all_sections()
        section = next((s for s in all_sections if s["slug"] == section_slug), None)

        if section is None:
            # Not a section - try as a root page instead
            page = get_help_page(section_slug, section="")
            if page is None:
                raise Http404("Page not found")

            # Render as a detail page
            self.template_name = "help/help_detail.html"
            context["page"] = page
            context["sections"] = all_sections
            context["current_section"] = ""
            context["section_pages"] = get_section_pages("")
            context["page_title"] = page["title"]

            # Find prev/next pages for navigation
            pages = context["section_pages"]
            current_idx = next(
                (i for i, p in enumerate(pages) if p["slug"] == section_slug),
                None,
            )
            if current_idx is not None:
                context["prev_page"] = pages[current_idx - 1] if current_idx > 0 else None
                context["next_page"] = pages[current_idx + 1] if current_idx < len(pages) - 1 else None
            return context

        context["section"] = section
        context["sections"] = all_sections
        context["current_section"] = section_slug
        context["page_title"] = section.get("title", "Documentation")
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


class SlideView(TemplateView):
    """Display a slide deck in presentation mode."""

    template_name = "help/slides.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        deck_slug = self.kwargs.get("deck_slug")
        content_root = self.request.GET.get("content_root")

        deck = get_slide_deck(deck_slug, content_root)
        if deck is None:
            raise Http404("Slide deck not found")

        slides = get_deck_slides(deck_slug, content_root)
        if not slides:
            raise Http404("Slide deck has no slides")

        context["deck"] = deck
        context["slides"] = slides
        context["page_title"] = deck.get("title", "Slides")
        return context


def search_index_view(request):
    """Return JSON search index for client-side search."""
    index = build_search_index()
    return JsonResponse({"pages": index})
