"""
Context processors for the admin theme.

Provides branding, site configuration, and palette data to all templates.
"""

from pathlib import Path

import yaml
from django.conf import settings

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

    return {
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
        "smallstack_version": _get_version(),
        "site": {
            "name": getattr(settings, "SITE_NAME", "SmallStack"),
            "domain": getattr(settings, "SITE_DOMAIN", "localhost:8000"),
            "use_https": getattr(settings, "USE_HTTPS", False),
        },
    }
