"""Context processors for smallstack-runbook."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from .conf import RUNBOOK_BASE_TEMPLATE


def runbook_settings(request: HttpRequest) -> dict[str, Any]:
    """Add runbook settings to template context."""
    return {
        "RUNBOOK_BASE_TEMPLATE": RUNBOOK_BASE_TEMPLATE,
    }
