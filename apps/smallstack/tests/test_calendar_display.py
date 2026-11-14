"""CalendarDisplay per-day render cap and the "+N more" drill-down.

A busy month used to render one chip (plus a hover-tooltip subtree) per record,
so a high-volume site produced tens of thousands of DOM nodes and a calendar
that took seconds to paint. Cells now render at most `max_per_day` chips and
link the remainder into a single-day panel.

The invariant these tests protect: capping is a RENDERING limit only. Counts
stay exact, so the header total and each "+N more" badge still describe the real
data — a cap that quietly under-reports would be worse than the slow page.
"""

import datetime as dt

import pytest
from django.test import RequestFactory

from apps.smallstack.crud import Action, CRUDView
from apps.smallstack.displays import CalendarDisplay
from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

MONTH = "2026-08"
DAY = dt.date(2026, 8, 12)


class _Cfg(CRUDView):
    model = APIToken
    list_fields = ["name"]
    url_base = "cal-tokens"
    actions = [Action.LIST]  # no DETAIL → chips render unlinked, no reversing


def _ctx(display, **params):
    request = RequestFactory().get("/", params)
    return display.get_context(APIToken.objects.all(), _Cfg, request)


def _cell(context, day: int):
    for week in context["weeks"]:
        for cell in week:
            if cell and cell["day"] == day:
                return cell
    raise AssertionError(f"day {day} not in grid")


@pytest.fixture
def busy_day(db):
    """40 tokens all landing on the same day."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username="calowner", password="x")
    stamp = dt.datetime.combine(DAY, dt.time(9, 0), tzinfo=dt.UTC)
    for i in range(40):
        token, _ = APIToken.create_token(
            user=user, name=f"cal-{i:02d}", token_type="manual", access_level="read"
        )
        APIToken.objects.filter(pk=token.pk).update(created_at=stamp)
    return user


def _display(**kwargs):
    return CalendarDisplay(date_field="created_at", title_field="name", **kwargs)


def test_cell_renders_at_most_max_per_day(busy_day):
    context = _ctx(_display(max_per_day=5), month=MONTH)
    cell = _cell(context, DAY.day)
    assert len(cell["events"]) == 5


def test_overflow_count_reports_the_remainder(busy_day):
    context = _ctx(_display(max_per_day=5), month=MONTH)
    cell = _cell(context, DAY.day)
    assert cell["overflow_count"] == 35
    assert cell["total_count"] == 40


def test_header_total_is_not_distorted_by_the_cap(busy_day):
    """The cap must never make the calendar under-report how much data exists."""
    context = _ctx(_display(max_per_day=5), month=MONTH)
    assert context["event_count"] == 40


def test_max_per_day_none_renders_everything(busy_day):
    """Back-compat escape hatch for callers that want the old behavior."""
    context = _ctx(_display(max_per_day=None), month=MONTH)
    cell = _cell(context, DAY.day)
    assert len(cell["events"]) == 40
    assert cell["overflow_count"] == 0


def test_rendered_chip_count_is_bounded_by_volume(busy_day):
    """The whole point: chips rendered stay flat as records grow."""
    context = _ctx(_display(max_per_day=5), month=MONTH)
    rendered = sum(
        len(cell["events"]) for week in context["weeks"] for cell in week if cell
    )
    assert rendered <= 5 * 31
    assert rendered < context["event_count"]


# --------------------------------------------------------------------------
# The drill-down
# --------------------------------------------------------------------------


def test_selected_day_returns_the_full_uncapped_list(busy_day):
    context = _ctx(_display(max_per_day=5), month=MONTH, day=DAY.isoformat())
    assert context["selected_day"] == DAY
    assert len(context["selected_day_events"]) == 40
    # …while the grid cell for that day stays capped
    assert len(_cell(context, DAY.day)["events"]) == 5


def test_selected_day_marks_its_cell(busy_day):
    context = _ctx(_display(max_per_day=5), month=MONTH, day=DAY.isoformat())
    assert _cell(context, DAY.day)["is_selected"] is True
    assert _cell(context, DAY.day + 1)["is_selected"] is False


def test_no_day_param_means_no_panel(busy_day):
    context = _ctx(_display(max_per_day=5), month=MONTH)
    assert context["selected_day"] is None
    assert context["selected_day_events"] == []


@pytest.mark.parametrize("bad", ["not-a-date", "2026-13-99", "", "2026-09-01"])
def test_unparseable_or_out_of_month_day_is_ignored(busy_day, bad):
    """A hand-edited ?day= must not 500 or leak another month into the panel."""
    context = _ctx(_display(max_per_day=5), month=MONTH, day=bad)
    assert context["selected_day"] is None
    assert context["selected_day_events"] == []


# --------------------------------------------------------------------------
# Timezone-correct month boundaries
# --------------------------------------------------------------------------


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_datetime_field_is_not_filtered_with_a_naive_boundary(busy_day):
    """Django warns when a DateTimeField is compared against a naive datetime.

    Passing a plain `date` did exactly that, and Django then coerced it with the
    *default* timezone while the bucketing side used `localtime()` (the
    *current* one) — two clocks deciding what "in this month" means. Raising on
    the warning is the assertion: it fires during queryset evaluation.
    """
    context = _ctx(_display(max_per_day=5), month=MONTH)
    assert context["event_count"] == 40


@pytest.mark.filterwarnings("error::RuntimeWarning")
def test_ranged_calendar_is_also_naive_free(busy_day):
    """The end_field branch builds its own boundary and must be converted too."""
    display = CalendarDisplay(
        date_field="created_at", end_field="expires_at", title_field="name"
    )
    _ctx(display, month=MONTH)  # evaluation happens inside get_context


def test_boundary_is_aware_for_datetime_fields_and_a_date_for_date_fields():
    from apps.smallstack.displays import _day_boundary, _is_datetime_field

    assert _is_datetime_field(APIToken, "created_at") is True
    bound = _day_boundary(DAY, True)
    assert bound.tzinfo is not None, "DateTimeField bound must be aware"
    assert (bound.year, bound.month, bound.day) == (DAY.year, DAY.month, DAY.day)
    assert (bound.hour, bound.minute) == (0, 0)
    # A non-datetime target keeps the plain date — that comparison is exact.
    assert _day_boundary(DAY, False) == DAY


def test_unresolvable_field_path_does_not_raise():
    """An annotation or property target falls back instead of guessing."""
    from apps.smallstack.displays import _is_datetime_field

    assert _is_datetime_field(APIToken, "no_such_field") is False
    assert _is_datetime_field(APIToken, "user__also__missing") is False


def test_related_datetime_path_is_detected():
    """Lookups may span relations — resolve to the field at the end of the path."""
    from apps.smallstack.displays import _is_datetime_field

    assert _is_datetime_field(APIToken, "user__date_joined") is True
    assert _is_datetime_field(APIToken, "user__username") is False
