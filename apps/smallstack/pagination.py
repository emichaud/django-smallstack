"""Reusable pagination utilities for SmallStack."""

from django.core.paginator import Paginator


def paginate_queryset(queryset, request, page_size=20, page_param="page"):
    """Paginate a queryset and return a Page object with display helpers.

    Works with regular querysets and .values().annotate() aggregations.
    Attaches convenience attributes to the returned Page object:
        - showing_start: 1-based index of first item on page
        - showing_end: 1-based index of last item on page
        - total_count: total number of items
        - page_range_display: elided page range for rendering
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

    page_obj = paginator.get_page(page_number)

    # Attach display helpers
    page_obj.showing_start = page_obj.start_index()
    page_obj.showing_end = page_obj.end_index()
    page_obj.total_count = paginator.count
    page_obj.page_range_display = paginator.get_elided_page_range(
        page_obj.number, on_each_side=2, on_ends=1
    )

    return page_obj


class PaginationMixin:
    """CBV mixin providing a paginate() helper method."""

    page_size = 20

    def paginate(self, queryset, page_size=None):
        return paginate_queryset(
            queryset, self.request, page_size=page_size or self.page_size
        )
