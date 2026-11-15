"""SmallStack's showcase pages: what the framework does, shown on a running site.

The about, getting-started, platform and prompts pages, the starter pages a
project copies from, and the public search page. None of it is your project's,
and nothing outside this app links to it unguarded, so a project deletes the
whole app once: the directory, ``"apps.showcase"`` in ``INSTALLED_APPS`` and its
``include()`` in ``config/urls.py``.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

EXAMPLE_ARTICLE_HIT: dict[str, Any] = {
    "display": "Shipping a search result that looks like the thing it found",
    "subtitle": (
        "A SearchBuilder lets one model return more than a title and a line of "
        "context. Here it carries the blog, the date, a reading time and tags."
    ),
    "snippet": "",
    "url": "#",
    "extra": {
        "card": "article",
        "blog": "Field Notes",
        "blog_url": "#",
        "published_at": "2026-10-11T09:00:00+00:00",
        "reading_minutes": 4,
        "tags": ["search", "crudview", "example"],
        "cover_url": "",
        "cover_alt": "",
        "is_featured": True,
    },
}


def search_view(request: HttpRequest) -> HttpResponse:
    """Public-site search.

    Open to everyone — including signed-out visitors. The registry
    applies the per-view ``search_access`` gate (and the optional
    ``search_visibility`` callback) given the request user, so the
    *page* is public but the *data* a given visitor can find is
    determined by what each CRUDView opted into:

      - Anonymous visitors see help docs plus any CRUDView with
        ``search_access = SearchAccess.ANONYMOUS``.
      - Authenticated users additionally see CRUDViews opted in to
        ``SearchAccess.AUTHENTICATED`` (often filtered per user via
        ``search_visibility``).
      - Staff see every registered view.

    The recipes — and an Inventory app walkthrough — are in
    ``apps/smallstack/docs/search.md``.
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
        # The "Shape a result" panel on the empty page renders one static
        # example of a SearchBuilder-shaped hit so the card is visible even on
        # an install with no published posts yet. Real hits carry the same
        # keys — see ``apps.blog.views.search_hit_for_post``.
        "example_article_hit": EXAMPLE_ARTICLE_HIT,
    }
    if query:
        hits = search_all(query, limit_per_model=limit_per_model, user=request.user)
        ctx["grouped"] = group_by_model(hits)
        ctx["total_hits"] = len(hits)
    else:
        ctx["grouped"] = []
        ctx["total_hits"] = 0
    return render(request, "showcase/search.html", ctx)


def about_view(request: HttpRequest) -> HttpResponse:
    """
    About page with embedded feature slide viewer.
    """
    from apps.help.utils import get_deck_slides, get_slide_deck

    deck = get_slide_deck("features")
    slides = get_deck_slides("features")
    return render(
        request,
        "showcase/about.html",
        {
            "deck": deck,
            "slides": slides or [],
        },
    )


def getting_started_view(request: HttpRequest) -> HttpResponse:
    """Getting Started guide for new users."""
    return render(request, "showcase/getting_started.html")


def starter_view(request: HttpRequest) -> HttpResponse:
    """Starter page demonstrating available components."""
    return render(request, "showcase/starter.html")


def starter_basic_view(request: HttpRequest) -> HttpResponse:
    """A minimal blank page — the simplest possible SmallStack page."""
    return render(request, "showcase/starter/basic.html")


def starter_forms_view(request: HttpRequest) -> HttpResponse:
    """Forms starter showing date pickers, alignment, and input patterns."""
    return render(request, "showcase/starter/forms.html")


@login_required
def starter_dashboard_view(request: HttpRequest) -> HttpResponse:
    """A page of your own built on SmallStack's dashboards: every template tag
    (``{% metric_card %}``, ``{% dashboard %}``, ``{% goal_list %}``, ``{% card %}``,
    ``{% report %}``) and the data tags a page uses to draw its own markup. Shows
    the first of each the viewer can open; ``seed_dashboards`` makes a demo."""
    from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Report

    def first(model: Any) -> Any:
        return model.objects.visible_to(request.user).active().order_by("name").first()

    metrics = list(Metric.objects.visible_to(request.user).active().exclude(period_field="").order_by("name")[:3])
    context = {
        "board": first(Dashboard),
        "metrics": metrics,
        "goal_list": first(GoalList),
        "card": first(Component),
        "report": first(Report),
    }
    return render(request, "showcase/starter/dashboard.html", context)


def starter_own_theme_view(request: HttpRequest) -> HttpResponse:
    """SmallStack's embeds on a base template that isn't ``smallstack/base.html``:
    a stand-in for a project's own theme, set up as ``adding-your-own-theme.md``
    says, with metric cards, a dashboard, a calendar and a help bubble on it."""
    from apps.dashboards.models import Dashboard, Metric

    metrics = list(Metric.objects.visible_to(request.user).active().exclude(period_field="").order_by("name")[:3])
    board = Dashboard.objects.visible_to(request.user).active().order_by("name").first()
    return render(request, "showcase/own_theme/page.html", {"metrics": metrics, "board": board})


def components_view(request: HttpRequest) -> HttpResponse:
    """Redirect to the components section in SmallStack docs."""
    return redirect(reverse("help:section_detail", kwargs={"section": "smallstack", "slug": "components"}))


# ---------------------------------------------------------------------------
# Platform pages — what the framework gives your app, and how to ask an agent
# ---------------------------------------------------------------------------


def platform_datasets_calendars_view(request: HttpRequest) -> HttpResponse:
    """Datasets and calendars: how they work, ready for your own apps."""
    return render(request, "showcase/platform_datasets_calendars.html")


def platform_blogs_newsletters_view(request: HttpRequest) -> HttpResponse:
    """Blogs and newsletters: the built-in publishing surface."""
    return render(request, "showcase/platform_blogs_newsletters.html")


def faq_view(request: HttpRequest) -> HttpResponse:
    """What SmallStack can build, by who is asking: builders, component users, integrators."""
    return render(request, "showcase/faq.html")


def prompts_view(request: HttpRequest) -> HttpResponse:
    """Copy-ready prompts for coding agents, by task."""
    return render(request, "showcase/prompts.html")
