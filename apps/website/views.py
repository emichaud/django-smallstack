"""
Website views - customize these for your project.

This app is the designated place for project-specific pages like
your homepage, landing pages, about page, etc.

These pages are intentionally separated from SmallStack core so you
can customize them freely without conflicts when pulling upstream updates.
"""

from django.shortcuts import redirect, render
from django.urls import reverse


def home_view(request):
    """
    Project homepage.

    Customize this view and its template (templates/website/home.html)
    for your project's landing page.
    """
    return render(request, "website/home.html")


def about_view(request):
    """
    About page with embedded feature slide viewer.
    """
    from apps.help.utils import get_deck_slides, get_slide_deck

    deck = get_slide_deck("features")
    slides = get_deck_slides("features")
    return render(
        request,
        "website/about.html",
        {
            "deck": deck,
            "slides": slides or [],
        },
    )


def getting_started_view(request):
    """Getting Started guide for new users."""
    return render(request, "website/getting_started.html")


def starter_view(request):
    """Starter page demonstrating available components."""
    return render(request, "starter.html")


def starter_basic_view(request):
    """A minimal blank page — the simplest possible SmallStack page."""
    return render(request, "starter/basic.html")


def starter_forms_view(request):
    """Forms starter showing date pickers, alignment, and input patterns."""
    return render(request, "starter/forms.html")


def components_view(request):
    """Redirect to the components section in help docs."""
    return redirect(reverse("help:section_index", kwargs={"section": "components"}))
