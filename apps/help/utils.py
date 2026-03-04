"""
Markdown processing utilities for the help system.

Supports hierarchical documentation with sections (folders).
Loads from two sources:
  - content/ - User's project documentation (conflict-free)
  - smallstack/ - SmallStack bundled documentation (controlled by setting)
"""

import html
import logging
import re
from pathlib import Path

import markdown
import yaml
from django.conf import settings

logger = logging.getLogger(__name__)

CONTENT_DIR = Path(__file__).parent / "content"
DOCS_DIR = Path(__file__).parent / "smallstack"
SMALLSTACK_SECTION_SLUG = "smallstack"


def is_smallstack_docs_enabled() -> bool:
    """Check if SmallStack docs should be shown."""
    return getattr(settings, "SMALLSTACK_DOCS_ENABLED", True)


def get_smallstack_config() -> dict:
    """Load SmallStack docs configuration from bundled docs."""
    if not is_smallstack_docs_enabled():
        return {}

    config_path = DOCS_DIR / "_config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_config() -> dict:
    """Load and return the help configuration (user docs only)."""
    config_path = CONTENT_DIR / "_config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            # Filter out any smallstack section reference (cleanup for old configs)
            if "sections" in config:
                config["sections"] = [
                    s
                    for s in config["sections"]
                    if s.get("slug") != SMALLSTACK_SECTION_SLUG
                ]
            return config
    return {"sections": [], "variables": {}}


def get_section_config(section: str) -> dict:
    """Load configuration for a specific section."""
    if not section:
        return get_config()

    # SmallStack section comes from bundled docs
    if section == SMALLSTACK_SECTION_SLUG:
        if is_smallstack_docs_enabled():
            return get_smallstack_config()
        return {"pages": [], "variables": {}}

    # User sections from content/
    config_path = CONTENT_DIR / section / "_config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"pages": [], "variables": {}}


def get_variables(section: str = "") -> dict:
    """Get merged variables from root and section configs."""
    root_config = get_config()
    variables = root_config.get("variables", {}).copy()

    if section:
        section_config = get_section_config(section)
        variables.update(section_config.get("variables", {}))

    return variables


def substitute_variables(content: str, section: str = "", extra_vars: dict = None) -> str:
    """
    Replace {{ variable }} placeholders with values from config.

    Uses a simple regex-based substitution that's safer than running
    content through Django's template engine.
    """
    variables = get_variables(section)
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


def get_help_page(slug: str, section: str = "") -> dict | None:
    """
    Load and render a help page by slug.

    Args:
        slug: The page slug (filename without .md)
        section: Optional section folder name

    Returns None if the page doesn't exist.
    """
    # Determine the correct directory
    if section == SMALLSTACK_SECTION_SLUG:
        if not is_smallstack_docs_enabled():
            return None
        file_path = DOCS_DIR / f"{slug}.md"
    elif section:
        file_path = CONTENT_DIR / section / f"{slug}.md"
    else:
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
    content = substitute_variables(content, section)

    # Render markdown
    rendered = render_markdown(content)

    # Get page config from section or root config
    if section:
        config = get_section_config(section)
    else:
        # For root pages, check the root section in sections list
        root_config = get_config()
        root_section = next(
            (s for s in root_config.get("sections", []) if s.get("slug") == ""),
            {},
        )
        config = {"pages": root_section.get("pages", [])}

    page_config = next(
        (p for p in config.get("pages", []) if p.get("slug") == slug),
        {},
    )

    return {
        "slug": slug,
        "section": section,
        "title": frontmatter.get("title") or page_config.get("title") or slug.replace("-", " ").title(),
        "description": frontmatter.get("description") or page_config.get("description", ""),
        "content": rendered["html"],
        "toc": rendered["toc"],
        "toc_tokens": rendered["toc_tokens"],
        "is_faq": page_config.get("is_faq", False),
        "icon": page_config.get("icon", ""),
        "meta": frontmatter,
    }


def get_section_pages(section: str) -> list:
    """Get all pages for a specific section."""
    # SmallStack section
    if section == SMALLSTACK_SECTION_SLUG:
        if not is_smallstack_docs_enabled():
            return []
        config = get_smallstack_config()
        folder = DOCS_DIR
    elif section:
        config = get_section_config(section)
        folder = CONTENT_DIR / section
    else:
        # Root section from main config
        root_config = get_config()
        root_section = next(
            (s for s in root_config.get("sections", []) if s.get("slug") == ""),
            {},
        )
        config = {"pages": root_section.get("pages", [])}
        folder = CONTENT_DIR

    pages = []
    for page_config in config.get("pages", []):
        slug = page_config.get("slug")
        file_path = folder / f"{slug}.md"
        if file_path.exists():
            pages.append(
                {
                    "slug": slug,
                    "section": section,
                    "title": page_config.get("title", slug.replace("-", " ").title()),
                    "description": page_config.get("description", ""),
                    "icon": page_config.get("icon", ""),
                    "is_faq": page_config.get("is_faq", False),
                }
            )

    return pages


def get_all_sections() -> list:
    """Get all sections with their metadata from both user and SmallStack docs."""
    config = get_config()
    sections = []

    # User sections from content/
    for section_config in config.get("sections", []):
        slug = section_config.get("slug", "")

        # Warn if user has a smallstack folder while SmallStack docs enabled
        if slug == SMALLSTACK_SECTION_SLUG and is_smallstack_docs_enabled():
            logger.warning(
                f"User section '{SMALLSTACK_SECTION_SLUG}' is hidden because "
                "SMALLSTACK_DOCS_ENABLED=True. Disable SmallStack docs or rename your section."
            )
            continue

        sections.append(
            {
                "slug": slug,
                "title": section_config.get("title", slug.replace("-", " ").title() if slug else "Documentation"),
                "description": section_config.get("description", ""),
                "pages": get_section_pages(slug),
            }
        )

    # Append SmallStack section if enabled
    if is_smallstack_docs_enabled():
        ss_config = get_smallstack_config()
        if ss_config:
            sections.append(
                {
                    "slug": SMALLSTACK_SECTION_SLUG,
                    "title": ss_config.get("title", "SmallStack Reference"),
                    "description": ss_config.get("description", ""),
                    "pages": get_section_pages(SMALLSTACK_SECTION_SLUG),
                }
            )

    return sections


def get_all_pages() -> list:
    """Get all help pages across all sections in configured order."""
    pages = []
    for section in get_all_sections():
        pages.extend(section["pages"])
    return pages


def build_search_index() -> list:
    """Build a simple search index for client-side search."""
    index = []
    for section in get_all_sections():
        for page in section["pages"]:
            page_data = get_help_page(page["slug"], page.get("section", ""))
            if page_data:
                # Strip HTML tags for plain text search
                text = re.sub(r"<[^>]+>", "", page_data["content"])
                text = html.unescape(text)
                # Limit text for performance
                index.append(
                    {
                        "slug": page["slug"],
                        "section": page.get("section", ""),
                        "title": page["title"],
                        "text": text[:2000],
                    }
                )
    return index
