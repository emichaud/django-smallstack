"""The 2026-11-08 refinement round: what an agent (MCP, REST) or a reviewer
found saying ok while doing something else, or answering 500."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.components import normalize_layout
from apps.dashboards.forms import DashboardForm
from apps.dashboards.models import Dashboard, Metric
from apps.dashboards.periods import comparison_target
from apps.dashboards.tests.test_dashboards import DS_AUTH, _call, _seed

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff():
    return User.objects.create_user("rr_staff", password="x", is_staff=True)


@pytest.fixture
def board(staff):
    _seed()
    Metric(key="rr_req", name="Requests", dataset=DS_AUTH, period_field="timestamp").save()
    d = Dashboard(name="RR", slug="rr", owner=staff, layout=[{"id": "c1", "type": "metric", "metric": "rr_req"}])
    d.save()
    return d


@pytest.mark.parametrize("agg", ["median", "count_distinct"])
def test_a_card_of_its_own_refuses_an_aggregation_that_doesnt_exist(agg):
    _seed()
    cell = {"type": "metric", "dataset": DS_AUTH, "agg": agg, "measure": "path"}
    _cells, problems = normalize_layout([cell])
    assert any("agg: use one of" in p for p in problems), problems


def test_a_null_cell_is_refused_not_dropped():
    _cells, problems = normalize_layout([None])
    assert problems == ["layout[0]: expected an object, not null"]


def test_layout_null_doesnt_empty_a_dashboard(board, staff):
    form = DashboardForm(
        data={"name": board.name, "slug": board.slug, "visibility": "personal", "layout": None},
        instance=board,
        user=staff,
    )
    assert not form.is_valid()
    assert "send [] to empty" in str(form.errors)


def test_this_month_compares_against_all_of_last_month():
    assert comparison_target("this_month", "pmtd").startswith("all of")
    assert comparison_target("this_year", "prev_year").startswith("all of")


def test_archiving_a_row_that_stopped_validating_isnt_a_500(board):
    # A metric the dashboard draws went personal since; the layout no longer
    # validates, but archiving writes one column and must still work.
    Dashboard.objects.filter(pk=board.pk).update(
        layout=[{"id": "a", "type": "metric", "metric": "rr_req"}, {"id": "a", "type": "metric", "metric": "rr_req"}]
    )
    board.refresh_from_db()
    board.set_archived(True)
    board.refresh_from_db()
    assert board.is_archived


def test_a_dashboard_changing_hands_starts_unshared(board, staff):
    other = User.objects.create_user("rr_other", password="x")
    board.shared_with_everyone = True
    board.save()
    board.shared_with.add(other)
    board.owner = None  # made shared (ownerless) ...
    board.save()
    board.owner = staff  # ... then taken personal again
    board.save()
    board.refresh_from_db()
    assert not board.shared_with_everyone and not board.shared_with.exists()


def test_a_dashboard_keeping_its_owner_keeps_its_sharing(board):
    other = User.objects.create_user("rr_keep", password="x")
    board.shared_with.add(other)
    board.name = "Renamed"
    board.save()
    assert board.shared_with.filter(pk=other.pk).exists()


def test_the_component_list_names_the_options_every_card_shares(staff):
    got = _call("list_dashboard_components", {}, staff)
    assert {"publish", "listen", "style", "thresholds"} <= set(got["shared_options"])
