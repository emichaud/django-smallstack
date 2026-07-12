"""Reusable pagination utilities for SmallStack."""

from typing import Any

from django.core.paginator import Page, Paginator
from django.http import HttpRequest


def attach_display_helpers(page_obj: Page) -> Page:
    """Attach SmallStack's four list-pagination display attributes to a Page.

    Every HTML list-render path — :func:`paginate_queryset` here, the CRUDView
    display protocol (``displays.paginate_queryset``), and the legacy CRUD table
    path (``crud.py``) — needs the same four attributes so templates render
    identical pager controls. Centralizing the attachment keeps them from
    drifting apart: the June-2026 ``page_range_display`` regression happened when
    one path attached only three of the four.

        - showing_start: 1-based index of the first item on the page
        - showing_end: 1-based index of the last item on the page
        - total_count: total number of items across all pages
        - page_range_display: elided page range, materialized as a list so it can
          be iterated more than once (``get_elided_page_range`` yields a one-shot
          generator that silently empties on second iteration)
    """
    paginator = page_obj.paginator
    page_obj.showing_start = page_obj.start_index()
    page_obj.showing_end = page_obj.end_index()
    page_obj.total_count = paginator.count
    page_obj.page_range_display = list(
        paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    )
    return page_obj


def paginate_queryset(queryset: Any, request: HttpRequest, page_size: int = 20, page_param: str = "page") -> Page:
    """Paginate a queryset and return a Page object with display helpers.

    Works with regular querysets and .values().annotate() aggregations.
    Attaches the four SmallStack display attributes via
    :func:`attach_display_helpers`.
    """
    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get(page_param, 1)

    try:
        page_number = int(page_number)
    except (TypeError, ValueError):
        page_number = 1

    if page_number < 1:
        page_number = 1
    elif page_number > paginator.num_pages:
        page_number = paginator.num_pages

    return attach_display_helpers(paginator.get_page(page_number))


class PaginationMixin:
    """CBV mixin providing a paginate() helper method."""

    page_size = 20

    def paginate(self, queryset: Any, page_size: int | None = None) -> Page:
        return paginate_queryset(queryset, self.request, page_size=page_size or self.page_size)
