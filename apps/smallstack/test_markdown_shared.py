"""The shared markdown renderer + frontmatter parser in ``apps.smallstack.transforms``.

One hardened renderer serves runbook documents, blog posts and the CRUD
field-preview modal, so its guarantees are asserted here rather than in each
consumer. The XSS neutralization itself is covered by
``tests.py::test_markdown_preview_neutralizes_xss``; this module covers the
options surface (``extensions`` / ``toc``) and the frontmatter split, plus the
property that an ``extensions`` override cannot opt *out* of hardening.
"""

from __future__ import annotations

import markdown
import pytest

from apps.smallstack.transforms import (
    harden_markdown_renderer,
    parse_frontmatter,
    render_markdown,
    split_frontmatter,
)


class TestRenderMarkdown:
    def test_defaults_render_structure_and_toc(self):
        out = render_markdown("# Title\n\n## Sub\n\nBody **bold**")
        assert "<h1" in out["html"] and "<strong>" in out["html"]
        assert out["toc"]
        assert [t["name"] for t in out["toc_tokens"]] == ["Title"]
        assert out["toc_tokens"][0]["children"][0]["name"] == "Sub"

    def test_toc_false_omits_toc_but_keeps_html(self):
        out = render_markdown("# Title\n\nBody", toc=False)
        assert "<h1" in out["html"]
        assert out["toc"] == ""
        assert out["toc_tokens"] == []

    def test_toc_has_no_permalink_anchors_but_keeps_ids(self):
        """Permalinks are off (runbook's choice) while ids stay, so deep links work."""
        out = render_markdown("# My Heading")
        assert 'id="my-heading"' in out["html"]
        assert "header-link" not in out["html"]

    def test_default_extensions_cover_tables_and_fenced_code(self):
        assert "<table" in render_markdown("| a | b |\n|---|---|\n| 1 | 2 |")["html"]
        assert "<code" in render_markdown("```\nx = 1\n```")["html"]

    def test_extensions_override_replaces_the_default_set(self):
        out = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |", extensions=["fenced_code"])
        assert "<table" not in out["html"]

    @pytest.mark.parametrize("unsafe", ["attr_list", "legacy_attrs", "md_in_html"])
    def test_extensions_override_refuses_stored_xss_extensions(self, unsafe):
        """The override must not be usable to weaken the sanitizer.

        Hardening strips raw HTML and bad URL schemes; it cannot strip authored
        *attributes*, so ``attr_list`` really does yield a live ``onclick=`` —
        verified below against a raw renderer. Hence the hard refusal.
        """
        with pytest.raises(ValueError, match="stored-XSS"):
            render_markdown("# H", extensions=[unsafe, "fenced_code"])

    def test_attr_list_would_otherwise_inject_an_event_handler(self):
        """Pins *why* the refusal above exists: with attr_list enabled, the
        hardened renderer still emits onclick=. If this ever stops being true,
        the refusal can be revisited — until then it is load-bearing."""
        renderer = markdown.Markdown(extensions=["attr_list"])
        harden_markdown_renderer(renderer)
        assert "onclick" in renderer.convert('# H {: onclick="alert(1)"}')

    def test_safe_extension_override_is_allowed(self):
        """A legitimate override (here: dropping tables) still works."""
        out = render_markdown("```\nx\n```", extensions=["fenced_code"], toc=False)
        assert "<code" in out["html"]

    def test_empty_input_is_safe(self):
        out = render_markdown("")
        assert out["html"] == ""
        assert out["toc_tokens"] == []


class TestSplitFrontmatter:
    def test_splits_block_from_body(self):
        raw, body = split_frontmatter("---\ntitle: Hello\nslug: hi\n---\n\n# Body\n")
        assert "title: Hello" in raw
        assert body == "# Body"

    def test_no_frontmatter_returns_empty_block(self):
        raw, body = split_frontmatter("# Just a doc\n")
        assert raw == ""
        assert body == "# Just a doc"

    def test_thematic_break_is_not_frontmatter(self):
        """A genuine ``---`` rule with prose between the fences must survive —
        this is why the parser is not ``text.split("---", 2)``."""
        text = "---\nthis is prose, not key: value pairs\nand more prose\n---\n\nBody"
        raw, body = split_frontmatter(text)
        assert raw == ""
        assert body == text.strip()

    def test_tolerates_bom_and_crlf(self):
        raw, body = split_frontmatter("﻿---\r\ntitle: X\r\n---\r\n\r\nBody\r\n")
        assert "title: X" in raw
        assert body == "Body"

    def test_leading_image_is_kept_in_body(self):
        """An image pasted at the top is a common way frontmatter gets pushed
        below line 1; the block is still found and the image stays in the body."""
        raw, body = split_frontmatter("![alt](/x.png)\n---\ntitle: X\n---\n\nBody")
        assert "title: X" in raw
        assert body.startswith("![alt](/x.png)")
        assert "title: X" not in body


class TestParseFrontmatter:
    def test_returns_mapping_and_body(self):
        meta, body = parse_frontmatter("---\ntitle: Hello\ncount: 3\n---\n\nBody")
        assert meta == {"title": "Hello", "count": 3}
        assert body == "Body"

    def test_absent_frontmatter_yields_empty_mapping(self):
        meta, body = parse_frontmatter("# Doc")
        assert meta == {}
        assert body == "# Doc"

    def test_malformed_yaml_degrades_without_losing_the_body(self):
        """Broken frontmatter must never cost us the document body."""
        meta, body = parse_frontmatter("---\ntitle: 'unclosed\n---\n\nBody")
        assert meta == {}
        assert body == "Body"

    def test_non_mapping_frontmatter_yields_empty_mapping(self):
        meta, body = parse_frontmatter("---\njust: a\nvalid: map\n---\nBody")
        assert isinstance(meta, dict)
        assert body == "Body"
