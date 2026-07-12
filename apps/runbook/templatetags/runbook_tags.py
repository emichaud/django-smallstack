"""Template tags for smallstack-runbook.

Provides the RUNBOOK_BASE_TEMPLATE context variable to all templates.
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

from apps.runbook.conf import RUNBOOK_BASE_TEMPLATE

register = template.Library()


@register.simple_tag
def runbook_base_template() -> str:
    """Return the configured base template path."""
    return RUNBOOK_BASE_TEMPLATE


@register.simple_tag
def runbook_css() -> str:
    """URL for runbook.css with a cache-busting ``?v=<mtime>`` query.

    The dev static URL is unhashed, so browsers cache it and miss CSS edits until
    a hard refresh. Appending the file's modification time makes the URL change
    whenever the stylesheet does, so updates are picked up automatically.
    """
    url = static("runbook/runbook.css")
    path = finders.find("runbook/runbook.css")
    if path and os.path.exists(path):
        return f"{url}?v={int(os.path.getmtime(path))}"
    return url
