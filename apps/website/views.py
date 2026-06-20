"""
Website views - customize these for your project.

This app is the designated place for project-specific pages like
your homepage, landing pages, about page, etc.

These pages are intentionally separated from SmallStack core so you
can customize them freely without conflicts when pulling upstream updates.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse


@login_required
def search_view(request: HttpRequest) -> HttpResponse:
    """Public-site search — uses the editorial "Find anything" design
    (serif-italic display + Swagger-style indexed sources) rendered
    inside the website topbar/nav. The admin /smallstack/search/ uses
    the dashboard-style variant.

    Auth: any logged-in user (anonymous → /accounts/login/).

    Data access: the registry applies the per-view security knobs
    (``search_requires_staff`` + ``search_visibility``) given the
    request user. By default, CRUDViews are staff-only, so non-staff
    users searching here see only help docs plus any CRUDView that has
    explicitly opted in to non-staff search. See
    ``apps/smallstack/docs/search.md`` for the recipes.
    """
    # Imported lazily so collectstatic / migrate-only invocations don't
    # trigger search backend initialization.
    from apps.search.registry import get_indexed_sources, search_all, view_count
    from apps.search.views import group_by_model

    query = (request.GET.get("q") or "").strip()
    limit_per_model = int(request.GET.get("limit_per_model") or 10)

    ctx: dict[str, Any] = {
        "query": query,
        "registered_models": view_count(),
        "indexed_sources": get_indexed_sources(user=request.user),
    }
    if query:
        hits = search_all(query, limit_per_model=limit_per_model, user=request.user)
        ctx["grouped"] = group_by_model(hits)
        ctx["total_hits"] = len(hits)
    else:
        ctx["grouped"] = []
        ctx["total_hits"] = 0
    return render(request, "website/search.html", ctx)


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
    """Redirect to the components section in SmallStack docs."""
    return redirect(reverse("help:section_detail", kwargs={"section": "smallstack", "slug": "components"}))
