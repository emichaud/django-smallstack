"""
Website views - customize these for your project.

This app is the designated place for project-specific pages like
your homepage, landing pages, about page, etc.

These pages are intentionally separated from SmallStack core so you
can customize them freely without conflicts when pulling upstream updates.
"""

from django.shortcuts import render


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
    return render(request, "website/about.html", {
        "deck": deck,
        "slides": slides or [],
    })
