"""Regression tests for robust frontmatter stripping (CRLF + displaced blocks)."""

from apps.runbook.models import strip_frontmatter


def test_crlf_frontmatter():
    text = "---\r\ntitle: FAQ\r\ndescription: q\r\n---\r\n\r\n# Body\r\n"
    assert strip_frontmatter(text) == "# Body"


def test_image_displaced_frontmatter_kept_image_dropped_block():
    # An image inserted above the frontmatter pushes it below line 1.
    text = "![](/runbook/images/8/)\n\n---\ntitle: FAQ\ndescription: q\n---\n\n# Heading\n"
    out = strip_frontmatter(text)
    assert "title: FAQ" not in out
    assert "![](/runbook/images/8/)" in out
    assert "# Heading" in out


def test_leading_bom_and_frontmatter():
    text = "﻿---\nkey: val\n---\n# Body"
    assert strip_frontmatter(text) == "# Body"


def test_thematic_break_with_prose_not_stripped():
    # A real --- thematic break with prose (not key:value) must be preserved.
    text = "intro\n\n---\njust some prose\n---\n\nmore"
    assert strip_frontmatter(text) == text.strip()


def test_setext_heading_not_stripped():
    text = "Title\n---\nbody"
    assert strip_frontmatter(text) == "Title\n---\nbody"
