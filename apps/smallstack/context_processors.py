"""
Context processors for the admin theme.

Provides branding, site configuration, and palette data to all templates.
"""

import logging
import warnings
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
            resolved.append(
                {
                    "label": item["label"],
                    "children": resolved_children,
                    "has_active_child": has_active_child,
                }
            )
        else:
            # Leaf item
            resolved_url = _resolve_url(item)
            if resolved_url is None:
                continue
            active = _is_active(resolved_url, request.path)
            resolved.append(
                {
                    "label": item["label"],
                    "url": resolved_url,
                    "active": active,
                    "external": item.get("external", False),
                }
            )

    return resolved


def _get_sidebar_state(request):
    """Resolve the effective sidebar state.

    Precedence (highest to lowest):
    1. View context — request._smallstack_sidebar_state (set by view)
    2. Global setting — SMALLSTACK_SIDEBAR_DEFAULT

    Template blocks and localStorage are handled client-side.
    """
    # Check if view set a forced state
    view_state = getattr(request, "_smallstack_sidebar_state", None)
    if view_state is not None:
        return view_state, True  # (state, forced)

    # Fall back to global default
    default = getattr(settings, "SMALLSTACK_SIDEBAR_DEFAULT", "open")

    # Backward compat: map old boolean settings to new state string
    sidebar_enabled = getattr(settings, "SMALLSTACK_SIDEBAR_ENABLED", True)
    if not sidebar_enabled:
        return "disabled", True

    sidebar_open = getattr(settings, "SMALLSTACK_SIDEBAR_OPEN", True)
    if not sidebar_open and default == "open":
        default = "closed"

    return default, False


def branding(request):
    """
    Add branding configuration to template context.

    This allows templates to access brand assets and settings
    without hardcoding paths. Override these settings to customize
    the branding for your project.
    """
    system_palette = getattr(settings, "SMALLSTACK_COLOR_PALETTE", "django")
    effective_palette = _get_effective_palette(request)

    # Deprecation warning for old topbar nav settings
    topbar_nav_enabled = getattr(settings, "SMALLSTACK_TOPBAR_NAV_ENABLED", False)
    topbar_nav_items = []
    if topbar_nav_enabled:
        raw_items = getattr(settings, "SMALLSTACK_TOPBAR_NAV_ITEMS", [])
        if raw_items:
            warnings.warn(
                "SMALLSTACK_TOPBAR_NAV_ITEMS and SMALLSTACK_TOPBAR_NAV_ENABLED are "
                "deprecated. Register nav items via the nav registry instead. "
                "These settings will be removed in a future version.",
                DeprecationWarning,
                stacklevel=1,
            )
        topbar_nav_items = _resolve_nav_items(raw_items, request)

    # Sidebar state
    sidebar_state, sidebar_state_forced = _get_sidebar_state(request)
    sidebar_enabled = getattr(settings, "SMALLSTACK_SIDEBAR_ENABLED", True)

    # Nav items from registry (smallstack zone for sidebar/topbar)
    nav_items = nav.get_nav_items(request, zone="smallstack")
    website_nav_items = nav.get_nav_items(request, zone="website")

    # Check if special sections exist in nav_items (for template logic)
    nav_has_app_section = any(g["section"] == "app" for g in nav_items)
    nav_has_page_section = any(g["section"] == "page" for g in nav_items)
    nav_has_topbar_section = any(g["section"] == "topbar" for g in nav_items)

    topbar_nav_always = getattr(settings, "SMALLSTACK_TOPBAR_NAV_ALWAYS", False)

    return {
        "smallstack_topbar_nav_always": topbar_nav_always,
        "smallstack_topbar_nav_enabled": topbar_nav_enabled,
        "smallstack_topbar_nav_items": topbar_nav_items,
        "smallstack_docs_enabled": getattr(settings, "SMALLSTACK_DOCS_ENABLED", True),
        "smallstack_login_enabled": getattr(settings, "SMALLSTACK_LOGIN_ENABLED", True),
        "smallstack_signup_enabled": getattr(settings, "SMALLSTACK_SIGNUP_ENABLED", True),
        "smallstack_sidebar_enabled": sidebar_enabled,
        "smallstack_sidebar_default": sidebar_state,
        "sidebar_state": sidebar_state,
        "sidebar_state_forced": sidebar_state_forced,
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
        "nav_items": nav_items,
        "website_nav_items": website_nav_items,
        "nav_has_app_section": nav_has_app_section,
        "nav_has_page_section": nav_has_page_section,
        "nav_has_topbar_section": nav_has_topbar_section,
        "smallstack_version": _get_version(),
        "site": {
            "name": getattr(settings, "SITE_NAME", "SmallStack"),
            "domain": getattr(settings, "SITE_DOMAIN", "localhost:8000"),
            "use_https": getattr(settings, "USE_HTTPS", False),
        },
    }
