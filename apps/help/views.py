"""
Views for the help/documentation app.

Supports hierarchical documentation with sections (folders).
"""

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.views.generic import TemplateView

from .utils import (
    SMALLSTACK_SECTION_SLUG,
    build_search_index,
    get_all_sections,
    get_config,
    get_deck_slides,
    get_help_page,
    get_section_pages,
    get_section_pages_grouped,
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
        context["grouped_pages"] = get_section_pages_grouped(section_slug)
        context["page_title"] = section.get("title", "Documentation")
        return context


class HelpSectionTocView(TemplateView):
    """Display a dense table of contents for a section, grouped by category."""

    template_name = "help/help_toc.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        section_slug = self.kwargs.get("section")

        all_sections = get_all_sections()
        section = next((s for s in all_sections if s["slug"] == section_slug), None)

        if section is None:
            raise Http404("Section not found")

        grouped_pages = get_section_pages_grouped(section_slug)
        total_pages = sum(len(g["pages"]) for g in grouped_pages)

        context["section"] = section
        context["sections"] = all_sections
        context["current_section"] = section_slug
        context["grouped_pages"] = grouped_pages
        context["total_pages"] = total_pages
        context["page_title"] = f"{section.get('title', 'Documentation')} — Table of contents"
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
        context["section_pages_grouped"] = get_section_pages_grouped(section)
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


def search_index_view(request: HttpRequest) -> JsonResponse:
    """Return JSON search index for client-side search."""
    index = build_search_index()
    return JsonResponse({"pages": index})


# ---------------------------------------------------------------------------
# Agent-readable surfaces: page.md alternates, /llms.txt, /llms-full.txt
# ---------------------------------------------------------------------------


def _markdown_response(page: dict | None) -> HttpResponse:
    if page is None:
        raise Http404("Help page not found")
    return HttpResponse(page["markdown"] + "\n", content_type="text/markdown; charset=utf-8")


def help_page_markdown(request: HttpRequest, slug: str, section: str = "") -> HttpResponse:
    """``/smallstack/help/<section>/<slug>.md`` — the page as Markdown. What
    the HTML page's ``<link rel="alternate" type="text/markdown">`` points at,
    per the llms.txt convention."""
    from .utils import get_help_page_markdown

    return _markdown_response(get_help_page_markdown(slug, section))


def _site_name() -> str:
    from django.conf import settings

    return str(getattr(settings, "BRAND_NAME", None) or getattr(settings, "SITE_NAME", None) or "SmallStack")


def _site_blurb() -> str:
    from django.conf import settings

    return str(
        getattr(settings, "SMALLSTACK_LLMS_DESCRIPTION", None)
        or "A Django SmallStack site: an admin shell, REST API, MCP server, datasets, calendars, "
        "scheduler, webhooks, approvals and publishing, built on one model declaration per feature. "
        "The documentation below is served as Markdown."
    )


def _abs(request: HttpRequest, path: str) -> str:
    return request.build_absolute_uri(path)


def llms_txt(request: HttpRequest) -> HttpResponse:
    """``/llms.txt`` (https://llmstxt.org): an H1, a blockquote summary, then
    one H2 per help section whose entries link the Markdown version of each
    page, and an Optional section for the machine surfaces."""
    from django.urls import reverse

    from .utils import get_all_sections

    lines = [f"# {_site_name()}", "", f"> {_site_blurb()}", ""]
    lines.append(
        "Pages are listed per documentation section; every link is a Markdown rendering of the page. "
        "The same pages are readable as HTML under the same path without the `.md` suffix."
    )
    lines.append("")
    for section in get_all_sections():
        pages = section.get("pages") or []
        if not pages:
            continue
        lines.append(f"## {section['title']}")
        lines.append("")
        for page in pages:
            slug = page["slug"]
            if section["slug"]:
                path = reverse("help:section_detail_md", kwargs={"section": section["slug"], "slug": slug})
            else:
                path = reverse("help:detail_md", kwargs={"slug": slug})
            desc = (page.get("description") or "").strip()
            lines.append(f"- [{page['title']}]({_abs(request, path)})" + (f": {desc}" if desc else ""))
        lines.append("")
    lines.append("## Optional")
    lines.append("")
    full = _abs(request, reverse("llms_full_txt"))
    lines.append(f"- [Everything in one file]({full}): every page above, concatenated")
    lines.append(f"- [OpenAPI schema]({_abs(request, '/api/schema/openapi.json')}): the REST API of this site")
    lines.append(f"- [MCP endpoint]({_abs(request, '/mcp')}): JSON-RPC + OAuth for AI agents")
    lines.append(f"- [Status]({_abs(request, '/status/')}): public uptime page")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/markdown; charset=utf-8")


def llms_full_txt(request: HttpRequest) -> HttpResponse:
    """``/llms-full.txt``: every help page's Markdown, concatenated, each under
    its section and with a line naming its canonical URL."""
    from django.urls import reverse

    from .utils import get_all_sections, get_help_page_markdown

    parts = [f"# {_site_name()}", "", f"> {_site_blurb()}", ""]
    for section in get_all_sections():
        for page in section.get("pages") or []:
            md = get_help_page_markdown(page["slug"], section["slug"])
            if md is None:
                continue
            if section["slug"]:
                path = reverse("help:section_detail", kwargs={"section": section["slug"], "slug": page["slug"]})
            else:
                path = reverse("help:detail", kwargs={"slug": page["slug"]})
            parts.append("---")
            parts.append("")
            parts.append(f"<!-- {section['title']} · {_abs(request, path)} -->")
            parts.append("")
            parts.append(md["markdown"].rstrip())
            parts.append("")
    return HttpResponse("\n".join(parts) + "\n", content_type="text/markdown; charset=utf-8")

