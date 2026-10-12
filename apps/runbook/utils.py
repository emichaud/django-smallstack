"""Rendering utilities for Runbook documents."""

from __future__ import annotations

import re
from typing import TypedDict

# The markdown renderer and its RenderedMarkdown type live in the framework core
# (apps.smallstack.transforms) so runbook, blog and the CRUD field preview all
# share one hardened renderer. Re-exported here for the existing call sites.
from apps.smallstack.transforms import RenderedMarkdown, render_markdown  # noqa: F401

from .models import Document, strip_frontmatter


class RenderedContent(TypedDict):
    html: str
    toc: str
    raw: str


class SlideData(TypedDict):
    title: str
    html: str


class StepData(TypedDict):
    number: int
    title: str
    content_html: str
    notes: list[str]


def render_document(document: Document) -> RenderedContent:
    """Render a document to HTML based on its file_type."""
    if document.is_markdown and document.file is not None:
        raw = document.file.read().decode("utf-8")
        document.file.seek(0)
        content = strip_frontmatter(raw)
        rendered = render_markdown(content)
        return {"html": rendered["html"], "toc": rendered["toc"], "raw": content}

    return {"html": "<p>Unsupported file type.</p>", "toc": "", "raw": ""}


def parse_slides(raw_markdown: str) -> list[SlideData]:
    """Split markdown on ``---`` separators into slide HTML.

    Each slide gets a title extracted from its first ``# heading``,
    falling back to "Slide N" if no heading is found.
    """
    slides_raw = re.split(r"\n---\n", raw_markdown)
    slides: list[SlideData] = []
    for i, slide_md in enumerate(slides_raw):
        slide_md = slide_md.strip()
        if not slide_md:
            continue
        rendered = render_markdown(slide_md)
        title_match = re.match(r"^#\s+(.+)", slide_md, re.MULTILINE)
        title = title_match.group(1) if title_match else f"Slide {i + 1}"
        slides.append({"title": title, "html": rendered["html"]})
    return slides


def parse_steps(raw_markdown: str) -> list[StepData]:
    """Parse ``## Step N: Title`` format into structured steps.

    Extracts ``> note:`` blockquotes as callout notes and removes them
    from the rendered content.
    """
    pattern = r"^##\s+Step\s+(\d+):\s*(.+)$"
    parts = re.split(pattern, raw_markdown, flags=re.MULTILINE)

    steps: list[StepData] = []
    # parts[0] is preamble content before first step heading.
    # After that, groups of 3: (number, title, content).
    i = 1
    while i < len(parts):
        number = int(parts[i])
        title = parts[i + 1].strip()
        content = parts[i + 2] if i + 2 < len(parts) else ""
        i += 3

        # Extract > note: blockquotes as callout notes
        notes: list[str] = []
        note_pattern = r">\s*note:\s*(.+?)(?=\n[^>]|\n\n|\Z)"
        for match in re.finditer(note_pattern, content, re.IGNORECASE | re.DOTALL):
            notes.append(match.group(1).strip())

        # Remove note blockquotes from content for rendering
        clean_content = re.sub(
            r">\s*note:\s*.+?(?=\n[^>]|\n\n|\Z)", "", content, flags=re.IGNORECASE | re.DOTALL
        )

        rendered = render_markdown(clean_content.strip())
        steps.append({
            "number": number,
            "title": title,
            "content_html": rendered["html"],
            "notes": notes,
        })

    return steps
