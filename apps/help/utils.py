"""
Markdown processing utilities for the help system.
"""

import html
import re
from pathlib import Path

import markdown
import yaml

CONTENT_DIR = Path(__file__).parent / "content"


def get_config() -> dict:
    """Load and return the help configuration."""
    config_path = CONTENT_DIR / "_config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"pages": [], "variables": {}}


def substitute_variables(content: str, extra_vars: dict = None) -> str:
    """
    Replace {{ variable }} placeholders with values from config.

    Uses a simple regex-based substitution that's safer than running
    content through Django's template engine.
    """
    config = get_config()
    variables = config.get("variables", {})
    if extra_vars:
        variables.update(extra_vars)

    def replace_var(match):
        var_name = match.group(1).strip()
        return str(variables.get(var_name, match.group(0)))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace_var, content)


def render_markdown(content: str) -> dict:
    """
    Render markdown content to HTML with table of contents.

    Returns a dict with:
        - html: The rendered HTML content
        - toc: HTML table of contents
        - toc_tokens: Structured TOC data
    """
    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "toc",
            "attr_list",
            "md_in_html",
        ],
        extension_configs={
            "toc": {
                "permalink": True,
                "permalink_class": "header-link",
                "title": "Link to this section",
            },
        },
    )
    rendered_html = md.convert(content)
    return {
        "html": rendered_html,
        "toc": getattr(md, "toc", ""),
        "toc_tokens": getattr(md, "toc_tokens", []),
    }


def get_help_page(slug: str) -> dict | None:
    """
    Load and render a help page by slug.

    Returns None if the page doesn't exist.
    """
    file_path = CONTENT_DIR / f"{slug}.md"
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        raw_content = f.read()

    # Extract YAML frontmatter if present
    frontmatter = {}
    content = raw_content
    if raw_content.startswith("---"):
        parts = raw_content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            content = parts[2].strip()

    # Substitute variables
    content = substitute_variables(content)

    # Render markdown
    rendered = render_markdown(content)

    # Get page config from _config.yaml
    config = get_config()
    page_config = next(
        (p for p in config.get("pages", []) if p.get("slug") == slug),
        {},
    )

    return {
        "slug": slug,
        "title": frontmatter.get("title") or page_config.get("title") or slug.replace("-", " ").title(),
        "description": frontmatter.get("description") or page_config.get("description", ""),
        "content": rendered["html"],
        "toc": rendered["toc"],
        "toc_tokens": rendered["toc_tokens"],
        "is_faq": page_config.get("is_faq", False),
        "icon": page_config.get("icon", ""),
        "meta": frontmatter,
    }


def get_all_pages() -> list:
    """Get all help pages in configured order."""
    config = get_config()
    pages = []

    for page_config in config.get("pages", []):
        slug = page_config.get("slug")
        file_path = CONTENT_DIR / f"{slug}.md"
        if file_path.exists():
            pages.append(
                {
                    "slug": slug,
                    "title": page_config.get("title", slug.replace("-", " ").title()),
                    "description": page_config.get("description", ""),
                    "icon": page_config.get("icon", ""),
                    "is_faq": page_config.get("is_faq", False),
                }
            )

    return pages


def build_search_index() -> list:
    """Build a simple search index for client-side search."""
    index = []
    for page in get_all_pages():
        page_data = get_help_page(page["slug"])
        if page_data:
            # Strip HTML tags for plain text search
            text = re.sub(r"<[^>]+>", "", page_data["content"])
            text = html.unescape(text)
            # Limit text for performance
            index.append(
                {
                    "slug": page["slug"],
                    "title": page["title"],
                    "text": text[:2000],
                }
            )
    return index
