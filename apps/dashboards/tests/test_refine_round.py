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


@pytest.mark.parametrize("url", ["/\\evil.example", "//evil.example"])
def test_a_menu_link_that_leaves_the_site_isnt_a_page_of_it(url):
    from apps.dashboards.components import menu_url_problem

    # A browser reads "/\evil.example" as "//evil.example": off-site, drawn as local.
    assert menu_url_problem(url)
    assert menu_url_problem("/smallstack/") == ""


def test_openapi_says_what_a_layout_is(client):
    # A REST-only agent found `"layout": {}` and had to learn the cell shape
    # from existing boards; a form field's help text is now its description.
    from django.urls import reverse

    props = client.get(reverse("api-openapi-schema")).json()["components"]["schemas"]["Dashboard"]["properties"]
    assert "12-column grid" in props["layout"]["description"]
    assert "replaces the whole list" in props["layout"]["description"]


def test_an_all_time_trend_by_day_draws_every_day_not_the_last_twelve(rf, staff):
    # A cold-start agent's "last two weeks" chart showed 12 days, labelled all time.
    from datetime import timedelta

    from django.utils import timezone

    from apps.activity.models import RequestLog
    from apps.dashboards.trends import metric_trend

    now = timezone.now()
    for d in range(14):
        row = RequestLog.objects.create(path=f"/t/{d}", method="GET", status_code=200, response_time_ms=1)
        RequestLog.objects.filter(pk=row.pk).update(timestamp=now - timedelta(days=d))
    metric = Metric(key="rr_days", name="Days", dataset=DS_AUTH, period_field="timestamp")
    request = rf.get("/")
    request.user = staff
    got = metric_trend(metric, request, None, "day")
    assert got["ok"], got
    assert len(got["points"]) == 14


def test_a_snapshot_gives_a_gauge_its_number(board, staff):
    board.layout = [{"id": "g", "type": "gauge", "metric": "rr_req", "options": {"min": 0, "max": 100}}]
    board.save()
    got = _call("dashboard_snapshot", {"dashboard": board.slug}, staff)
    assert got["cells"][0]["result"]["value"] is not None


def test_sharing_with_nobody_by_that_name_says_so(board, staff):
    got = _call("dashboard_share", {"dashboard": board.slug, "add": ["ghost_zz"]}, staff)
    assert got["unknown"] == ["ghost_zz"] and "no active user named 'ghost_zz'" in got["warning"]


def test_rest_archives_and_restores_a_dashboard(client, board, staff):
    # An agent asked to archive had no way to: archived_at was ignored, DELETE destroys.
    import json

    client.force_login(staff)
    url = f"/smallstack/api/dashboards/boards/{board.pk}/"
    r = client.patch(url, json.dumps({"archived": True}), content_type="application/json")
    assert r.status_code == 200, r.content
    board.refresh_from_db()
    assert board.is_archived and len(board.layout) == 1  # nothing else changed
    client.patch(url, json.dumps({"name": "Renamed"}), content_type="application/json")
    board.refresh_from_db()
    assert board.is_archived  # left out: kept as it is
    client.patch(url, json.dumps({"archived": False}), content_type="application/json")
    board.refresh_from_db()
    assert not board.is_archived


def test_saving_an_archived_dashboards_settings_page_keeps_it_archived(client, board, staff):
    board.set_archived(True)
    client.force_login(staff)
    url = f"/smallstack/dashboards/boards/{board.pk}/edit/"
    assert client.get(url).status_code == 200
    # The page posts no "archived" (it has its own Archive button), or an empty one.
    r = client.post(url, {"name": board.name, "slug": board.slug, "visibility": "personal", "archived": ""})
    assert r.status_code in (200, 302)
    board.refresh_from_db()
    assert board.is_archived


def test_rest_names_the_keys_a_write_didnt_take(client, board, staff):
    import json

    client.force_login(staff)
    r = client.patch(
        f"/smallstack/api/dashboards/boards/{board.pk}/",
        json.dumps({"name": "N", "archived_at": "2026-01-01T00:00:00Z", "ownr": 3}),
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()["ignored"] == ["archived_at", "ownr"]
    url = f"/smallstack/api/dashboards/boards/{board.pk}/"
    r = client.patch(url, json.dumps({"name": "M"}), content_type="application/json")
    assert "ignored" not in r.json()


def test_a_members_card_over_a_staff_only_dataset_doesnt_list_its_columns():
    from apps.dashboards.tests.test_dashboards import DS_STAFF

    member = User.objects.create_user("rr_member", password="x")
    cell = {"type": "bars", "dataset": DS_STAFF, "agg": "count", "options": {"dimension": "zzz"}}
    _cells, problems = normalize_layout([cell], owner_id=member.pk)
    assert problems == [f"layout[0].dataset: No dataset named {DS_STAFF!r} is registered."]
    staff = User.objects.create_user("rr_staff2", password="x", is_staff=True)
    _cells, problems = normalize_layout([{**cell, "options": {"dimension": "method"}}], owner_id=staff.pk)
    assert problems == []
