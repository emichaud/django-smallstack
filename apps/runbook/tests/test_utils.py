"""Tests for Runbook rendering utilities."""

from apps.runbook.utils import parse_slides, parse_steps, render_markdown


class TestRenderMarkdown:
    def test_basic_rendering(self):
        result = render_markdown("# Hello\n\nWorld")
        assert "<h1" in result["html"]
        assert "World" in result["html"]
        assert result["toc"]  # TOC generated for headings

    def test_fenced_code(self):
        result = render_markdown("```python\nprint('hi')\n```")
        assert "<code" in result["html"]
        assert "print" in result["html"]

    def test_tables(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = render_markdown(md)
        assert "<table>" in result["html"]

    def test_empty_content(self):
        result = render_markdown("")
        assert result["html"] == ""


class TestParseSlides:
    def test_basic_split(self):
        md = "# Slide 1\n\nContent\n\n---\n\n# Slide 2\n\nMore content"
        slides = parse_slides(md)
        assert len(slides) == 2
        assert slides[0]["title"] == "Slide 1"
        assert slides[1]["title"] == "Slide 2"
        assert "<p>Content</p>" in slides[0]["html"]

    def test_empty_slides_skipped(self):
        md = "# Only Slide\n\nContent\n\n---\n\n---\n\n"
        slides = parse_slides(md)
        assert len(slides) == 1

    def test_no_heading_fallback_title(self):
        md = "Just some text without a heading."
        slides = parse_slides(md)
        assert slides[0]["title"] == "Slide 1"

    def test_empty_input(self):
        slides = parse_slides("")
        assert slides == []


class TestParseSteps:
    def test_basic_steps(self):
        md = "# Title\n\n## Step 1: First\n\nDo this.\n\n## Step 2: Second\n\nDo that."
        steps = parse_steps(md)
        assert len(steps) == 2
        assert steps[0]["number"] == 1
        assert steps[0]["title"] == "First"
        assert steps[1]["number"] == 2
        assert steps[1]["title"] == "Second"

    def test_notes_extraction(self):
        md = "## Step 1: Setup\n\nContent here.\n\n> note: Remember to check credentials.\n\nMore content."
        steps = parse_steps(md)
        assert len(steps) == 1
        assert len(steps[0]["notes"]) == 1
        assert "credentials" in steps[0]["notes"][0]

    def test_empty_document(self):
        md = "# No steps here\n\nJust regular content."
        steps = parse_steps(md)
        assert len(steps) == 0

    def test_step_content_rendered_as_html(self):
        md = "## Step 1: Test\n\n**Bold text** here."
        steps = parse_steps(md)
        assert "<strong>Bold text</strong>" in steps[0]["content_html"]
