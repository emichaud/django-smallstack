"""
Utility views for the project.
"""

from django.http import HttpResponse
from django.shortcuts import render


def health_check(request):
    """Simple health check endpoint."""
    return HttpResponse("OK", content_type="text/plain")


def home_view(request):
    """Home/dashboard view."""
    return render(request, "home.html")


def starter_view(request):
    """
    Starter page demonstrating available components.

    Copy this view and the starter.html template to create new pages.
    """
    return render(request, "starter.html")
