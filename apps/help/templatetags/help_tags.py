"""Template tags for putting help beside the thing it explains."""

from __future__ import annotations

import logging
from typing import Any

from django import template

from ..utils import _resolve_bubble_url, _resolve_help_url, get_help_page_markdown

logger = logging.getLogger(__name__)
register = template.Library()


@register.inclusion_tag("help/includes/help_bubble_button.html")
def help_bubble(*path: str, label: str = "") -> dict[str, Any]:
    """A small "?" that opens a help page in the page's modal, without leaving it.

    Usage:
        {% load help_tags %}
        {% help_bubble "dashboards" "component" %}      a page of a section
        {% help_bubble "getting-started" %}              a root page
        {% help_bubble "dashboards" "component" label="What's a component?" %}

    The page is an ordinary help page (a markdown file the help system already
    serves), so the bubble and the full page can't drift apart. Keep one to a
    page and a half; its ``related`` and ``guide`` frontmatter fill the modal's
    footer (see ``utils.get_help_bubble``). Without JavaScript the link goes to
    the full page. A page that doesn't exist draws nothing, and logs a warning.
    """
    section, slug = (path[0], path[1]) if len(path) > 1 else ("", path[0] if path else "")
    page = get_help_page_markdown(slug, section) if slug else None
    if page is None:
        logger.warning("help_bubble: no help page %r in section %r", slug, section)
        return {"page": None}
    bubble_url = _resolve_bubble_url(slug, section)
    if not bubble_url:
        return {"page": None}
    return {"page": page, "bubble_url": bubble_url, "page_url": _resolve_help_url(slug, section), "label": label}
