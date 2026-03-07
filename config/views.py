"""
Utility views for the project.
"""

from django.http import HttpResponse
from django.shortcuts import render


def health_check(request):
    """Simple health check endpoint."""
    return HttpResponse("OK", content_type="text/plain")


def starter_view(request):
    """
    Starter page demonstrating available components.

    Copy this view and the starter.html template to create new pages.
    """
    return render(request, "starter.html")


def starter_basic_view(request):
    """A minimal blank page — the simplest possible SmallStack page."""
    return render(request, "starter/basic.html")


def starter_forms_view(request):
    """Forms starter showing date pickers, alignment, and input patterns."""
    return render(request, "starter/forms.html")
