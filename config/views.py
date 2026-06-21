"""
Utility views for the project.
"""

import logging
from pathlib import Path

from django.http import Http404
from django.shortcuts import render

from apps.help.utils import render_markdown

logger = logging.getLogger(__name__)

LEGAL_PAGES = {
    "privacy-policy": "Privacy Policy",
    "terms-of-service": "Terms of Service",
}


def legal_page_view(request, page):
    """Render a legal markdown page (privacy policy or terms of service)."""
    if page not in LEGAL_PAGES:
        raise Http404("Page not found")

    legal_dir = Path(__file__).resolve().parent.parent / "apps" / "website" / "content" / "legal"
    file_path = legal_dir / f"{page}.md"

    if not file_path.exists():
        raise Http404("Page not found")

    content = file_path.read_text(encoding="utf-8")
    rendered = render_markdown(content)

    return render(
        request,
        "legal/page.html",
        {
            "page_title": LEGAL_PAGES[page],
            "content": rendered["html"],
        },
    )


def health_check(request):
    """Health check endpoint with database connectivity test.

    In production this path is normally short-circuited by
    ``HealthCheckMiddleware`` (so proxy health checks bypass Host validation);
    this view backs the same URL for direct/local requests. Both delegate to
    the one shared ``health_response`` helper.
    """
    from apps.smallstack.middleware import health_response

    return health_response()
