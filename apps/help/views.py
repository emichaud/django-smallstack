"""
Views for the help/documentation app.
"""

from django.http import Http404, JsonResponse
from django.views.generic import TemplateView

from .utils import build_search_index, get_all_pages, get_config, get_help_page


class HelpIndexView(TemplateView):
    """Display the help documentation index."""

    template_name = "help/help_index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = get_config()
        context["pages"] = get_all_pages()
        context["page_title"] = config.get("title", "Help & Documentation")
        context["config"] = config
        return context


class HelpDetailView(TemplateView):
    """Display a single help page."""

    template_name = "help/help_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs.get("slug")

        page = get_help_page(slug)
        if page is None:
            raise Http404("Help page not found")

        context["page"] = page
        context["all_pages"] = get_all_pages()
        context["page_title"] = page["title"]

        # Find prev/next pages for navigation
        pages = context["all_pages"]
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
