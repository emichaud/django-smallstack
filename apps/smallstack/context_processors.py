"""
Context processors for the admin theme.

Provides branding, site configuration, and palette data to all templates.
"""

import logging
from pathlib import Path

import yaml
from django.conf import settings
from django.urls import NoReverseMatch, reverse

from apps.smallstack.navigation import nav

logger = logging.getLogger(__name__)

_cached_version = None


def _get_version():
    """Get SmallStack version from pyproject.toml."""
    global _cached_version
    if _cached_version is not None:
        return _cached_version
    try:
        pyproject = Path(settings.BASE_DIR) / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if line.startswith("version"):
                _cached_version = line.split('"')[1]
                return _cached_version
    except (FileNotFoundError, IndexError):
        pass
    _cached_version = ""
    return _cached_version


def _load_palettes():
    """Load palette definitions from palettes.yaml."""
    palette_file = Path(__file__).parent / "palettes.yaml"
    try:
        with open(palette_file) as f:
            data = yaml.safe_load(f)
        return data.get("palettes", [])
    except (FileNotFoundError, yaml.YAMLError):
        return []


def _get_effective_palette(request):
    """Resolve effective palette: user override > system default."""
    system_default = getattr(settings, "SMALLSTACK_COLOR_PALETTE", "django")

    if request.user.is_authenticated:
        try:
            user_palette = request.user.profile.color_palette
            if user_palette:
                return user_palette
        except Exception:
            pass

    return system_default


def _is_active(resolved_url, request_path):
    """Check if a resolved URL matches the current request path."""
    if request_path == resolved_url:
        return True
    if resolved_url != "/" and request_path.startswith(resolved_url):
        return True
    return False


def _resolve_url(item):
    """Resolve a nav item's URL. Returns the resolved URL string or None."""
    url = item.get("url", "")
    if not url:
        return None

    # External URLs and absolute paths pass through
    if url.startswith(("http://", "https://", "/")):
        return url

    # Try to reverse as a URL name
    try:
        url_args = item.get("url_args", [])
        return reverse(url, args=url_args)
    except NoReverseMatch:
        logger.debug("Topbar nav: could not reverse '%s', skipping", url)
        return None


def _resolve_nav_items(items, request):
    """Resolve nav items: filter by auth/staff, reverse URLs, determine active state."""
    resolved = []
    user = getattr(request, "user", None)
    is_authenticated = getattr(user, "is_authenticated", False)
    is_staff = getattr(user, "is_staff", False)

    for item in items:
        # Filter by auth/staff requirements
        if item.get("auth_required") and not is_authenticated:
            continue
        if item.get("staff_required") and not is_staff:
            continue

        children = item.get("children")
        if children:
            # Submenu parent
            resolved_children = _resolve_nav_items(children, request)
            if not resolved_children:
                continue
            has_active_child = any(c.get("active") for c in resolved_children)
            resolved.append({
                "label": item["label"],
                "children": resolved_children,
                "has_active_child": has_active_child,
            })
        else:
            # Leaf item
            resolved_url = _resolve_url(item)
            if resolved_url is None:
                continue
            active = _is_active(resolved_url, request.path)
            resolved.append({
                "label": item["label"],
                "url": resolved_url,
                "active": active,
                "external": item.get("external", False),
            })

    return resolved


def branding(request):
    """
    Add branding configuration to template context.

    This allows templates to access brand assets and settings
    without hardcoding paths. Override these settings to customize
    the branding for your project.

    Settings (in settings.py):
        BRAND_NAME: The display name for your site (default: "SmallStack")
        BRAND_LOGO: Path to the main logo SVG (relative to STATIC_URL)
        BRAND_LOGO_DARK: Path to the dark mode logo SVG
        BRAND_LOGO_TEXT: Path to text-only logo for topbar (32px height)
        BRAND_ICON: Path to the icon-only mark SVG
        BRAND_FAVICON: Path to the favicon ICO file
        BRAND_SOCIAL_IMAGE: Path to the OpenGraph/social preview image
        BRAND_TAGLINE: A short description of your site

    Logo Sizes:
        logo_text: Displayed at 32px height in topbar
        logo/logo_dark: For marketing pages (40-60px)
        icon: For small spaces (32-48px square)
        favicon: Browser tab (32x32, 16x16 ICO)
        social_image: OpenGraph preview (1200x630px PNG)

    Template usage:
        <link rel="icon" href="{% static brand.favicon %}">
        <img src="{% static brand.logo_text %}">  <!-- Topbar -->
        <img src="{% static brand.logo %}">       <!-- Marketing pages -->
        <meta property="og:image" content="{% static brand.social_image %}">
    """
    system_palette = getattr(settings, "SMALLSTACK_COLOR_PALETTE", "django")
    effective_palette = _get_effective_palette(request)

    topbar_nav_enabled = getattr(settings, "SMALLSTACK_TOPBAR_NAV_ENABLED", False)
    topbar_nav_items = []
    if topbar_nav_enabled:
        raw_items = getattr(settings, "SMALLSTACK_TOPBAR_NAV_ITEMS", [])
        topbar_nav_items = _resolve_nav_items(raw_items, request)

    return {
        "smallstack_topbar_nav_enabled": topbar_nav_enabled,
        "smallstack_topbar_nav_items": topbar_nav_items,
        "smallstack_docs_enabled": getattr(settings, "SMALLSTACK_DOCS_ENABLED", True),
        "smallstack_login_enabled": getattr(settings, "SMALLSTACK_LOGIN_ENABLED", True),
        "smallstack_signup_enabled": getattr(settings, "SMALLSTACK_SIGNUP_ENABLED", True),
        "smallstack_sidebar_enabled": getattr(settings, "SMALLSTACK_SIDEBAR_ENABLED", True),
        "smallstack_sidebar_open": getattr(settings, "SMALLSTACK_SIDEBAR_OPEN", True),
        "palettes": _load_palettes(),
        "color_palette": effective_palette,
        "system_color_palette": system_palette,
        "brand": {
            "name": getattr(settings, "BRAND_NAME", "SmallStack"),
            "logo": getattr(settings, "BRAND_LOGO", "smallstack/brand/django-smallstack-logo.svg"),
            "logo_dark": getattr(settings, "BRAND_LOGO_DARK", "smallstack/brand/django-smallstack-logo-dark.svg"),
            "logo_text": getattr(settings, "BRAND_LOGO_TEXT", "smallstack/brand/django-smallstack-text.svg"),
            "icon": getattr(settings, "BRAND_ICON", "smallstack/brand/django-smallstack-icon.svg"),
            "favicon": getattr(settings, "BRAND_FAVICON", "smallstack/brand/django-smallstack-icon.ico"),
            "social_image": getattr(settings, "BRAND_SOCIAL_IMAGE", "smallstack/brand/django-smallstack-social.png"),
            "tagline": getattr(settings, "BRAND_TAGLINE", "A minimal Django starter stack"),
            "privacy_url": getattr(settings, "BRAND_PRIVACY_URL", "/privacy/"),
            "terms_url": getattr(settings, "BRAND_TERMS_URL", "/terms/"),
            "cookie_banner": getattr(settings, "BRAND_COOKIE_BANNER", True),
            "signup_terms_notice": getattr(settings, "BRAND_SIGNUP_TERMS_NOTICE", True),
        },
        "nav_items": nav.get_nav_items(request),
        "smallstack_version": _get_version(),
        "site": {
            "name": getattr(settings, "SITE_NAME", "SmallStack"),
            "domain": getattr(settings, "SITE_DOMAIN", "localhost:8000"),
            "use_https": getattr(settings, "USE_HTTPS", False),
        },
    }
