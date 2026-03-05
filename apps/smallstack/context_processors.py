"""
Context processors for the admin theme.

Provides branding and site configuration to all templates.
"""

from django.conf import settings


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
    return {
        "smallstack_docs_enabled": getattr(settings, "SMALLSTACK_DOCS_ENABLED", True),
        "smallstack_login_enabled": getattr(settings, "SMALLSTACK_LOGIN_ENABLED", True),
        "smallstack_signup_enabled": getattr(settings, "SMALLSTACK_SIGNUP_ENABLED", True),
        "brand": {
            "name": getattr(settings, "BRAND_NAME", "SmallStack"),
            "logo": getattr(settings, "BRAND_LOGO", "smallstack/brand/django-smallstack-logo.svg"),
            "logo_dark": getattr(settings, "BRAND_LOGO_DARK", "smallstack/brand/django-smallstack-logo-dark.svg"),
            "logo_text": getattr(settings, "BRAND_LOGO_TEXT", "smallstack/brand/django-smallstack-text.svg"),
            "icon": getattr(settings, "BRAND_ICON", "smallstack/brand/django-smallstack-icon.svg"),
            "favicon": getattr(settings, "BRAND_FAVICON", "smallstack/brand/django-smallstack-icon.ico"),
            "social_image": getattr(settings, "BRAND_SOCIAL_IMAGE", "smallstack/brand/django-smallstack-social.png"),
            "tagline": getattr(settings, "BRAND_TAGLINE", "A minimal Django starter stack"),
        },
        "site": {
            "name": getattr(settings, "SITE_NAME", "SmallStack"),
            "domain": getattr(settings, "SITE_DOMAIN", "localhost:8000"),
            "use_https": getattr(settings, "USE_HTTPS", False),
        },
    }
