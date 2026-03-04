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
        BRAND_ICON: Path to the icon-only mark SVG
        BRAND_FAVICON: Path to the favicon ICO file
        BRAND_SOCIAL_IMAGE: Path to the OpenGraph/social preview image
        BRAND_TAGLINE: A short description of your site

    Template usage:
        <link rel="icon" href="{% static brand.favicon %}">
        <img src="{% static brand.logo %}">
        <meta property="og:image" content="{% static brand.social_image %}">
    """
    return {
        "brand": {
            "name": getattr(settings, "BRAND_NAME", "SmallStack"),
            "logo": getattr(settings, "BRAND_LOGO", "brand/django-smallstack-logo.svg"),
            "logo_dark": getattr(settings, "BRAND_LOGO_DARK", "brand/django-smallstack-logo-dark.svg"),
            "icon": getattr(settings, "BRAND_ICON", "brand/django-smallstack-icon.svg"),
            "favicon": getattr(settings, "BRAND_FAVICON", "brand/django-smallstack-icon.ico"),
            "social_image": getattr(settings, "BRAND_SOCIAL_IMAGE", "brand/django-smallstack-social.png"),
            "tagline": getattr(settings, "BRAND_TAGLINE", "A minimal Django starter stack"),
        },
        "site": {
            "name": getattr(settings, "SITE_NAME", "SmallStack"),
            "domain": getattr(settings, "SITE_DOMAIN", "localhost:8000"),
            "use_https": getattr(settings, "USE_HTTPS", False),
        },
    }
