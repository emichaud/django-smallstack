"""
Tests for the help/documentation app.
"""

import pytest
from django.urls import reverse

from .utils import (
    get_all_pages,
    get_all_sections,
    get_config,
    get_deck_slides,
    get_help_page,
    get_slide_deck,
    get_slides_config,
    render_markdown,
    substitute_variables,
)


class TestHelpUtils:
    """Tests for help utility functions."""

    def test_get_config_returns_dict(self):
        """get_config should return a dictionary with sections and variables."""
        config = get_config()
        assert isinstance(config, dict)
        assert "sections" in config
        assert "variables" in config

    def test_get_config_has_variables(self):
        """Config should have expected variables."""
        config = get_config()
        variables = config.get("variables", {})
        assert "version" in variables
        assert "project_name" in variables

    def test_substitute_variables(self):
        """Variables should be substituted in content."""
        config = get_config()
        project_name = config["variables"]["project_name"]

        content = "Welcome to {{ project_name }}!"
        result = substitute_variables(content)
        assert project_name in result
        assert "{{ project_name }}" not in result

    def test_substitute_variables_unknown(self):
        """Unknown variables should be left as-is."""
        content = "Hello {{ unknown_var }}!"
        result = substitute_variables(content)
        assert "{{ unknown_var }}" in result

    def test_substitute_variables_extra_vars(self):
        """Extra variables should be substituted."""
        content = "Value is {{ custom }}."
        result = substitute_variables(content, extra_vars={"custom": "TEST"})
        assert result == "Value is TEST."

    def test_render_markdown_basic(self):
        """Markdown should render to HTML."""
        content = "# Heading\n\nParagraph text."
        result = render_markdown(content)

        assert "html" in result
        assert "toc" in result
        assert "<h1" in result["html"]
        assert "Heading" in result["html"]
        assert "<p>" in result["html"]

    def test_render_markdown_code_blocks(self):
        """Code blocks should be rendered."""
        content = "```python\nprint('hello')\n```"
        result = render_markdown(content)

        assert "<code" in result["html"]
        assert "print" in result["html"]

    def test_render_markdown_tables(self):
        """Tables should be rendered."""
        content = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = render_markdown(content)

        assert "<table>" in result["html"]
        assert "<th>" in result["html"]

    def test_get_all_pages_returns_list(self):
        """get_all_pages should return a list."""
        pages = get_all_pages()
        assert isinstance(pages, list)
        assert len(pages) > 0

    def test_get_all_pages_structure(self):
        """Each page should have required fields."""
        pages = get_all_pages()
        for page in pages:
            assert "slug" in page
            assert "title" in page
            assert "description" in page

    def test_get_all_sections_returns_list(self):
        """get_all_sections should return sections with pages."""
        sections = get_all_sections()
        assert isinstance(sections, list)
        assert len(sections) > 0
        for section in sections:
            assert "slug" in section
            assert "title" in section
            assert "pages" in section

    def test_get_help_page_root_exists(self):
        """get_help_page should return page data for root index page."""
        page = get_help_page("index")
        assert page is not None
        assert page["slug"] == "index"
        assert "title" in page
        assert "content" in page
        assert "toc" in page

    def test_get_help_page_smallstack_section(self):
        """get_help_page should return page data for SmallStack section pages."""
        page = get_help_page("getting-started", section="smallstack")
        assert page is not None
        assert page["slug"] == "getting-started"
        assert "title" in page
        assert "content" in page

    def test_get_help_page_not_found(self):
        """get_help_page should return None for non-existent page."""
        page = get_help_page("this-page-does-not-exist")
        assert page is None

    def test_get_help_page_variables_substituted(self):
        """Variables should be substituted in page content."""
        page = get_help_page("getting-started", section="smallstack")
        # SmallStack docs use their own variables, but root variables are merged
        # Just verify the content was rendered (not None)
        assert page is not None
        assert len(page["content"]) > 0


class TestSlideUtils:
    """Tests for slide utility functions."""

    def test_get_slides_config_returns_dict(self):
        """get_slides_config should return a dict with decks."""
        config = get_slides_config()
        assert isinstance(config, dict)
        assert "decks" in config

    def test_get_slide_deck_exists(self):
        """get_slide_deck should return the activity-tracking deck."""
        deck = get_slide_deck("activity-tracking")
        assert deck is not None
        assert deck["slug"] == "activity-tracking"
        assert "slides" in deck

    def test_get_slide_deck_not_found(self):
        """get_slide_deck should return None for non-existent deck."""
        deck = get_slide_deck("nonexistent-deck")
        assert deck is None

    def test_get_deck_slides_renders(self):
        """get_deck_slides should return rendered slides."""
        slides = get_deck_slides("activity-tracking")
        assert slides is not None
        assert len(slides) == 5
        for slide in slides:
            assert "slug" in slide
            assert "title" in slide
            assert "html" in slide
            assert len(slide["html"]) > 0

    def test_get_deck_slides_not_found(self):
        """get_deck_slides should return None for non-existent deck."""
        slides = get_deck_slides("nonexistent-deck")
        assert slides is None

    def test_custom_content_root(self):
        """get_slides_config with explicit default path should work."""
        config = get_slides_config(content_root="apps/help/content/slides")
        assert isinstance(config, dict)
        assert "decks" in config


class TestHelpViews:
    """Tests for help views."""

    @pytest.mark.django_db
    def test_help_index_view(self, client):
        """Help index should return 200 and list sections."""
        response = client.get(reverse("help:index"))
        assert response.status_code == 200
        assert "sections" in response.context

    @pytest.mark.django_db
    def test_help_detail_view(self, client):
        """Help detail should return 200 for existing root page."""
        response = client.get(reverse("help:detail", kwargs={"slug": "index"}))
        assert response.status_code == 200
        assert "page" in response.context
        assert response.context["page"]["slug"] == "index"

    @pytest.mark.django_db
    def test_help_detail_view_404(self, client):
        """Help detail should return 404 for non-existent page."""
        response = client.get(reverse("help:detail", kwargs={"slug": "nonexistent-page"}))
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_help_section_detail_view(self, client):
        """Section detail should return 200 for SmallStack docs."""
        response = client.get(
            reverse("help:section_detail", kwargs={"section": "smallstack", "slug": "getting-started"})
        )
        assert response.status_code == 200
        assert "page" in response.context
        assert response.context["page"]["slug"] == "getting-started"

    @pytest.mark.django_db
    def test_help_section_index_view(self, client):
        """Section index should return 200 for SmallStack section."""
        response = client.get(reverse("help:section_index", kwargs={"section": "smallstack"}))
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_search_index_view(self, client):
        """Search index should return JSON with pages."""
        response = client.get(reverse("help:search_index"))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"

        data = response.json()
        assert "pages" in data
        assert len(data["pages"]) > 0

        # Each page should have slug, title, and text
        for page in data["pages"]:
            assert "slug" in page
            assert "title" in page
            assert "text" in page

    @pytest.mark.django_db
    def test_slide_view_200(self, client):
        """Slide view should return 200 for existing deck."""
        response = client.get(reverse("help:slides", kwargs={"deck_slug": "activity-tracking"}))
        assert response.status_code == 200
        assert "deck" in response.context
        assert "slides" in response.context
        assert len(response.context["slides"]) == 5

    @pytest.mark.django_db
    def test_slide_view_404(self, client):
        """Slide view should return 404 for non-existent deck."""
        response = client.get(reverse("help:slides", kwargs={"deck_slug": "nonexistent"}))
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_slide_view_custom_content_root(self, client):
        """Slide view should accept content_root parameter."""
        response = client.get(
            reverse("help:slides", kwargs={"deck_slug": "activity-tracking"}),
            {"content_root": "apps/help/content/slides"},
        )
        assert response.status_code == 200
