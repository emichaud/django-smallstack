"""
Tests for the help/documentation app.
"""

import pytest
from django.urls import reverse

from .utils import (
    get_all_pages,
    get_config,
    get_help_page,
    render_markdown,
    substitute_variables,
)


class TestHelpUtils:
    """Tests for help utility functions."""

    def test_get_config_returns_dict(self):
        """get_config should return a dictionary."""
        config = get_config()
        assert isinstance(config, dict)
        assert "pages" in config
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

    def test_get_help_page_exists(self):
        """get_help_page should return page data for existing page."""
        page = get_help_page("getting-started")
        assert page is not None
        assert page["slug"] == "getting-started"
        assert "title" in page
        assert "content" in page
        assert "toc" in page

    def test_get_help_page_not_found(self):
        """get_help_page should return None for non-existent page."""
        page = get_help_page("this-page-does-not-exist")
        assert page is None

    def test_get_help_page_variables_substituted(self):
        """Variables should be substituted in page content."""
        page = get_help_page("getting-started")
        config = get_config()
        project_name = config["variables"]["project_name"]

        # The content should have the project name, not the variable syntax
        assert project_name in page["content"]


class TestHelpViews:
    """Tests for help views."""

    @pytest.mark.django_db
    def test_help_index_view(self, client):
        """Help index should return 200 and list pages."""
        response = client.get(reverse("help:index"))
        assert response.status_code == 200
        assert "pages" in response.context
        assert len(response.context["pages"]) > 0

    @pytest.mark.django_db
    def test_help_detail_view(self, client):
        """Help detail should return 200 for existing page."""
        response = client.get(reverse("help:detail", kwargs={"slug": "getting-started"}))
        assert response.status_code == 200
        assert "page" in response.context
        assert response.context["page"]["slug"] == "getting-started"

    @pytest.mark.django_db
    def test_help_detail_view_404(self, client):
        """Help detail should return 404 for non-existent page."""
        response = client.get(reverse("help:detail", kwargs={"slug": "nonexistent-page"}))
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_help_detail_has_navigation(self, client):
        """Help detail should have prev/next navigation."""
        response = client.get(reverse("help:detail", kwargs={"slug": "getting-started"}))
        assert response.status_code == 200
        # First page should have next but not prev
        assert response.context.get("prev_page") is None
        assert response.context.get("next_page") is not None

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
