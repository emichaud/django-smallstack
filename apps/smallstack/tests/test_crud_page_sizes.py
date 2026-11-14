"""``CRUDView.page_sizes`` — the opt-in "Rows per page" choice on HTML lists.

Unset, a list pages at ``paginate_by`` exactly as before. Set, ``?per_page=``
picks one of the choices (anything else falls back to the first) and the
framework pager (``{% render_paginator %}``) shows the control.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory

from apps.smallstack.crud import NON_FILTER_QUERY_PARAMS, CRUDView
from apps.smallstack.pagination import PAGE_SIZE_CHOICES, page_size_from, paginate_queryset


class _Fixed(CRUDView):
    model = get_user_model()
    paginate_by = 30


class _Choosable(_Fixed):
    page_sizes = PAGE_SIZE_CHOICES


def _req(query: str = "") -> object:
    return RequestFactory().get(f"/list/{query}")


def test_without_page_sizes_the_list_keeps_paginate_by():
    assert _Fixed.page_size_for(_req("?per_page=50")) == 30


def test_with_page_sizes_the_request_chooses_from_them():
    assert PAGE_SIZE_CHOICES == (15, 25, 50, 100)
    assert _Choosable.page_size_for(_req()) == 15  # the first choice is the default
    assert _Choosable.page_size_for(_req("?per_page=50")) == 50
    assert _Choosable.page_size_for(_req("?per_page=7")) == 15  # never a free-form number
    assert _Choosable.page_size_for(_req("?per_page=lots")) == 15
    assert page_size_from(_req("?n=25"), (10, 25), param="n") == 25


def test_per_page_is_not_a_filter():
    """An empty list with only ?per_page= is empty, not filtered-to-empty."""
    assert "per_page" in NON_FILTER_QUERY_PARAMS


def _pager(page_sizes: tuple[int, ...], per_page: int | None, count: int, query: str = "") -> str:
    request = _req(query)
    page = paginate_queryset(list(range(count)), request, page_size=per_page or 15)
    return Template("{% load theme_tags %}{% render_paginator page_obj '#area' %}").render(
        Context({"request": request, "page_obj": page, "page_sizes": page_sizes, "per_page": per_page})
    )


def test_the_pager_offers_rows_per_page():
    html = _pager(PAGE_SIZE_CHOICES, 25, 40, "?q=ops&page=2&per_page=25")
    assert 'name="per_page"' in html and '<option value="25" selected>' in html
    assert 'hx-target="#area"' in html and 'hx-push-url="true"' in html
    # The no-JS form keeps the search but starts the new size at page 1.
    assert '<input type="hidden" name="q" value="ops">' in html and 'name="page" value' not in html


def test_the_control_stays_when_everything_fits_on_one_page():
    """Otherwise choosing a big size would hide the way back."""
    html = _pager(PAGE_SIZE_CHOICES, 25, 20)
    assert 'name="per_page"' in html and "paginator-nav" not in html


def test_no_pager_without_page_sizes_on_a_single_page():
    assert "paginator" not in _pager((), None, 10)
    assert 'name="per_page"' not in _pager((), None, 40)  # pages, but no size choice
