"""
Markdown processing utilities for the help system.

Supports hierarchical documentation with sections (folders).
Loads from multiple sources:
  - content/ - User's project documentation (conflict-free)
  - Per-app docs - Apps with help_content_dir attribute contribute docs
"""

import html
import logging
import re
from pathlib import Path

import markdown
import yaml
from django.apps import apps
from django.conf import settings

logger = logging.getLogger(__name__)

CONTENT_DIR = Path(__file__).parent / "content"
SLIDES_DIR = Path(__file__).parent / "content" / "slides"
SMALLSTACK_SECTION_SLUG = "smallstack"


def _get_app_help_sources() -> dict[str, dict]:
    """Discover help content directories from installed apps.

    Returns a dict mapping section slug to {"dir": Path, "title": str, "app_label": str}.
    Apps opt in by setting help_content_dir and help_section_slug on their AppConfig.
    """
    sources = {}
    for app_config in apps.get_app_configs():
        content_dir = getattr(app_config, "help_content_dir", None)
        section_slug = getattr(app_config, "help_section_slug", None)
        if content_dir and section_slug:
            docs_path = Path(app_config.path) / content_dir
            if docs_path.is_dir():
                sources[section_slug] = {
                    "dir": docs_path,
                    "title": getattr(app_config, "help_section_title", section_slug.replace("-", " ").title()),
                    "app_label": app_config.label,
                }
    return sources


def _get_section_dir(section: str) -> Path | None:
    """Resolve the directory for a section, checking app sources then content/."""
    if not section:
        return CONTENT_DIR

    # Check app-contributed docs
    app_sources = _get_app_help_sources()
    if section in app_sources:
        return app_sources[section]["dir"]

    # Fall back to content/ subdirectory
    content_path = CONTENT_DIR / section
    if content_path.is_dir():
        return content_path

    return None


def is_smallstack_docs_enabled() -> bool:
    """Check if SmallStack docs should be shown."""
    return getattr(settings, "SMALLSTACK_DOCS_ENABLED", True)


def get_smallstack_config() -> dict:
    """Load SmallStack docs configuration from bundled docs."""
    if not is_smallstack_docs_enabled():
        return {}

    section_dir = _get_section_dir(SMALLSTACK_SECTION_SLUG)
    if section_dir is None:
        return {}

    config_path = section_dir / "_config.yaml"
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
                config["sections"] = [s for s in config["sections"] if s.get("slug") != SMALLSTACK_SECTION_SLUG]
            return config
    return {"sections": [], "variables": {}}


def get_section_config(section: str) -> dict:
    """Load configuration for a specific section."""
    if not section:
        return get_config()

    # SmallStack section
    if section == SMALLSTACK_SECTION_SLUG:
        if is_smallstack_docs_enabled():
            return get_smallstack_config()
        return {"pages": [], "variables": {}}

    # Check app sources and content/ subdirectories
    section_dir = _get_section_dir(section)
    if section_dir is not None:
        config_path = section_dir / "_config.yaml"
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
    # SmallStack section gated on setting
    if section == SMALLSTACK_SECTION_SLUG and not is_smallstack_docs_enabled():
        return None

    # Resolve directory
    section_dir = _get_section_dir(section)
    if section_dir is None:
        return None

    if section:
        file_path = section_dir / f"{slug}.md"
    else:
        file_path = section_dir / f"{slug}.md"

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
    # SmallStack section gated on setting
    if section == SMALLSTACK_SECTION_SLUG and not is_smallstack_docs_enabled():
        return []

    # Resolve directory
    section_dir = _get_section_dir(section)
    if section_dir is None:
        return []

    if not section:
        # Root section from main config
        root_config = get_config()
        root_section = next(
            (s for s in root_config.get("sections", []) if s.get("slug") == ""),
            {},
        )
        config = {"pages": root_section.get("pages", [])}
        folder = CONTENT_DIR
    else:
        config = get_section_config(section)
        folder = section_dir

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
                    "category": page_config.get("category", ""),
                }
            )

    return pages


def get_section_pages_grouped(section: str) -> list[dict]:
    """Group pages by category using explicit category ordering from config.

    Returns [{"category": "Getting Started", "pages": [...]}, ...]

    Ordering rules:
    1. Categories appear in the order defined in the config's `categories:` list
    2. Pages within each category keep their config order
    3. Categories referenced by pages but NOT in the list -> appended alphabetically, with warning logged
    4. Pages with no category -> ungrouped bucket at end (category="")
    5. If no `categories:` list exists -> returns single group with all pages (flat)
    """
    pages = get_section_pages(section)
    config = get_section_config(section)
    defined_categories = config.get("categories", [])

    # No categories list -> flat rendering
    if not defined_categories:
        return [{"category": "", "pages": pages}]

    # Bucket pages by category
    buckets: dict[str, list] = {}
    for page in pages:
        cat = page.get("category", "")
        buckets.setdefault(cat, []).append(page)

    defined_set = set(defined_categories)
    result = []

    # 1. Defined categories in list order
    for cat in defined_categories:
        if cat in buckets:
            result.append({"category": cat, "pages": buckets[cat]})

    # 2. Unlisted categories (referenced by pages but not in the list), alphabetically
    unlisted = sorted(
        cat for cat in buckets if cat and cat not in defined_set
    )
    for cat in unlisted:
        logger.warning(
            "Category '%s' is referenced by pages in section '%s' "
            "but not defined in the categories list.",
            cat,
            section,
        )
        result.append({"category": cat, "pages": buckets[cat]})

    # 3. Uncategorized pages at the end
    if "" in buckets:
        result.append({"category": "", "pages": buckets[""]})

    return result


def get_all_sections() -> list:
    """Get all sections with their metadata from user docs, app docs, and SmallStack."""
    config = get_config()
    sections = []

    # User sections from content/
    for section_config in config.get("sections", []):
        slug = section_config.get("slug", "")

        # Skip slugs that are provided by app sources
        app_sources = _get_app_help_sources()
        if slug in app_sources:
            logger.warning(
                f"User section '{slug}' is hidden because app "
                f"'{app_sources[slug]['app_label']}' provides it. "
                "Rename your section to avoid the conflict."
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

    # Append app-contributed sections
    app_sources = _get_app_help_sources()
    for slug, source in app_sources.items():
        # SmallStack section gated on setting
        if slug == SMALLSTACK_SECTION_SLUG and not is_smallstack_docs_enabled():
            continue

        section_config = get_section_config(slug)
        if section_config:
            sections.append(
                {
                    "slug": slug,
                    "title": section_config.get("title", source["title"]),
                    "description": section_config.get("description", ""),
                    "pages": get_section_pages(slug),
                }
            )

    return sections


def get_all_pages() -> list:
    """Get all help pages across all sections in configured order."""
    pages = []
    for section in get_all_sections():
        pages.extend(section["pages"])
    return pages


def _resolve_slides_root(content_root: str | None = None) -> Path:
    """Resolve the slides content root directory.

    If content_root is given, it's treated as relative to BASE_DIR and
    validated to be within BASE_DIR for security.
    """
    if content_root:
        base_dir = Path(settings.BASE_DIR)
        resolved = (base_dir / content_root).resolve()
        if not str(resolved).startswith(str(base_dir.resolve())):
            raise ValueError("content_root must be within BASE_DIR")
        return resolved
    return SLIDES_DIR


def get_slides_config(content_root: str | None = None) -> dict:
    """Load _slides.yaml from the given root or default slides dir."""
    root = _resolve_slides_root(content_root)
    config_path = root / "_slides.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"decks": []}


def get_slide_deck(deck_slug: str, content_root: str | None = None) -> dict | None:
    """Get a single deck's config by slug."""
    config = get_slides_config(content_root)
    return next(
        (d for d in config.get("decks", []) if d.get("slug") == deck_slug),
        None,
    )


def get_deck_slides(deck_slug: str, content_root: str | None = None) -> list | None:
    """Load and render all slides for a deck.

    Returns a list of dicts with slug, title, and rendered html,
    or None if the deck doesn't exist.
    """
    deck = get_slide_deck(deck_slug, content_root)
    if deck is None:
        return None

    root = _resolve_slides_root(content_root)
    slides = []
    for slide_config in deck.get("slides", []):
        slug = slide_config.get("slug")
        file_path = root / deck_slug / f"{slug}.md"
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()
            content = substitute_variables(raw_content)
            rendered = render_markdown(content)
            slides.append(
                {
                    "slug": slug,
                    "title": slide_config.get("title", slug.replace("-", " ").title()),
                    "html": rendered["html"],
                }
            )
    return slides


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
