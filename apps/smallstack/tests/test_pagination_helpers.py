"""Regression: every list-pagination call site attaches the same four
SmallStack pagination display helpers, and `page_range_display` is a
re-iterable list (not a one-shot generator).

The same shape is documented in apps/smallstack/pagination.py:14-17 and
advertised to downstream projects building richer pager templates.
Three call sites attach these helpers — they must stay in sync:

  - apps/smallstack/displays.py:paginate_queryset
  - apps/smallstack/pagination.py:paginate_queryset
  - apps/smallstack/crud.py:_CRUDListBase legacy table path
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import Client, RequestFactory
from django.urls import reverse

User = get_user_model()
pytestmark = pytest.mark.django_db


REQUIRED_HELPERS = ("showing_start", "showing_end", "total_count", "page_range_display")


def _assert_helpers(page_obj):
    """Every page_obj reaching a template must carry all four helpers."""
    for attr in REQUIRED_HELPERS:
        assert hasattr(page_obj, attr), f"page_obj missing {attr!r}"
    # `page_range_display` must be re-iterable. A bare generator would
    # silently yield nothing on the second pass — see issue note.
    assert list(page_obj.page_range_display) == list(page_obj.page_range_display), (
        "page_range_display must be re-iterable (list, not generator)"
    )


# ---------------------------------------------------------------------------
# Path 1: apps.smallstack.pagination.paginate_queryset (direct caller)
# ---------------------------------------------------------------------------


def test_pagination_helpers_pagination_module():
    from apps.smallstack.pagination import paginate_queryset

    # Use a queryset big enough to fill multiple pages.
    qs = User.objects.order_by("pk")
    # Seed a few rows so we have something to paginate.
    [User.objects.create_user(username=f"p{i}", password="x") for i in range(7)]

    request = RequestFactory().get("/?page=1")
    page_obj = paginate_queryset(qs, request, page_size=2)
    _assert_helpers(page_obj)
    assert page_obj.total_count == 7
    # Materialized list — first elements are page numbers / ellipses.
    range_display = page_obj.page_range_display
    assert isinstance(range_display, list)
    assert len(range_display) > 0


# ---------------------------------------------------------------------------
# Path 2: apps.smallstack.displays.paginate_queryset (display-based lists)
# ---------------------------------------------------------------------------


def test_pagination_helpers_displays_module():
    from apps.smallstack.displays import paginate_queryset

    qs = User.objects.order_by("pk")
    [User.objects.create_user(username=f"d{i}", password="x") for i in range(5)]

    request = RequestFactory().get("/?page=1")
    ctx = paginate_queryset(qs, paginate_by=2, request=request)

    page_obj = ctx["page_obj"]
    _assert_helpers(page_obj)
    assert page_obj.total_count == 5
    assert isinstance(page_obj.page_range_display, list)


def test_pagination_helpers_displays_returns_unchanged_when_paginate_by_falsy():
    """Defensive: when paginate_by is falsy, the helper short-circuits.
    No page_obj at all in that case — and we shouldn't crash trying to
    attach helpers."""
    from apps.smallstack.displays import paginate_queryset

    request = RequestFactory().get("/")
    ctx = paginate_queryset(User.objects.order_by("pk"), paginate_by=0, request=request)
    assert "page_obj" not in ctx


# ---------------------------------------------------------------------------
# Path 3: legacy CRUDView list (_CRUDListBase.get_context_data)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pagination_helpers_crud_view_legacy_path():
    """Hit a real CRUDView list URL and inspect its context.
    TokenCRUDView is the simplest stable target — its `displays = []`
    (default) so it takes the legacy table path that we just patched.
    """
    from apps.smallstack.models import APIToken

    staff = User.objects.create_user(username="paginate_check", password="x", is_staff=True)
    # Seed enough tokens to trigger pagination (TokenCRUDView paginate_by=20).
    for i in range(25):
        APIToken.create_token(user=staff, name=f"tok-{i}", access_level="readonly")

    c = Client()
    c.force_login(staff)
    # ?is_active= disables the tokenmgr default to active-only, so all 25
    # tokens are visible across pages (the default is operative below the
    # paginate_by threshold otherwise).
    resp = c.get(reverse("tokenmgr:tokens-list") + "?is_active=", HTTP_HOST="localhost")
    assert resp.status_code == 200
    page_obj = resp.context["page_obj"]
    _assert_helpers(page_obj)
    assert page_obj.total_count >= 25


# ---------------------------------------------------------------------------
# Generator footgun — explicitly verify it's a list, not a generator
# ---------------------------------------------------------------------------


def test_page_range_display_is_list_not_generator():
    """Without the list-cast, the second iteration silently yields []."""
    import types

    from apps.smallstack.pagination import paginate_queryset

    [User.objects.create_user(username=f"g{i}", password="x") for i in range(6)]
    request: HttpRequest = RequestFactory().get("/?page=1")
    page_obj = paginate_queryset(User.objects.order_by("pk"), request, page_size=2)
    assert not isinstance(page_obj.page_range_display, types.GeneratorType)
    assert isinstance(page_obj.page_range_display, list)
