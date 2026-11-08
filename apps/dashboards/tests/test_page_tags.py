"""The dashboards on any page: whole-piece tags ({% goal_list %}, {% card %},
{% report %}) and the data tags a page draws its own markup from. Same access
rules as the pages: nothing for something the viewer may not open."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory

from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Report

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff():
    return User.objects.create_user("tags-staff", password="x", is_staff=True)


@pytest.fixture
def rows(staff):
    Metric(
        key="tg_requests", name="Tag requests", description="Every request.", dataset=DS, period_field="timestamp"
    ).save()
    Component(name="Tag card", key="tg_card", type="metric", metric="tg_requests").save()
    goals = [{"metric": "tg_requests", "target": {"op": ">=", "value": 0}}]
    GoalList(name="Tag goals", slug="tg-goals", sections=[{"title": "", "goals": goals}]).save()
    Report(name="Tag report", slug="tg-report", items=[{"metric": "tg_requests"}], periods=["mtd", "pmtd"]).save()
    Dashboard(
        name="Tag board",
        slug="tg-board",
        layout=[{"type": "metric", "metric": "tg_requests", "x": 0, "y": 0, "w": 3, "h": 2}],
    ).save()
    # Someone else's personal one: never shown to a member.
    owner = User.objects.create_user("tags-owner", password="x")
    GoalList(name="Private goals", slug="tg-private", owner=owner, sections=[]).save()


def render(source: str, user) -> str:
    request = RequestFactory().get("/somewhere/")
    request.user = user
    return Template("{% load dashboard_tags %}" + source).render(Context({"request": request}))


def test_the_whole_pieces_render_on_any_page(staff, rows):
    html = render('{% goal_list "tg-goals" %}', staff)
    assert "Tag goals" in html and "gl-board" in html and 'data-about="Every request."' in html
    assert "dashboards/js/about-info.js" in html and "dm-sort" not in html  # no page sorting off its page
    html = render('{% card "tg_card" %}', staff)
    assert "dash-embed-card" in html and "stat-card" in html and "min-height: 140px" in html
    assert "height: 300px" in render('{% card "tg_card" height=300 %}', staff)
    html = render('{% report "tg-report" title=False %}', staff)
    assert "rp-table" in html and "Tag requests" in html and 'class="sr-only">Tag report' in html
    assert "dm-sort" not in html  # the page sorts; an embed doesn't


def test_the_data_tags_give_the_engine_s_numbers(staff, rows):
    html = render(
        '{% metric_value "tg_requests" period="mtd" as m %}{{ m.metric.name }}={{ m.result.display }};'
        '{% metric_series "tg_requests" period="last_7" grain="day" as t %}{{ t.points|length }};'
        '{% goal_values "tg-goals" as g %}{{ g.summary.headline }};'
        '{% report_values "tg-report" as r %}{{ r.columns|length }};'
        '{% dashboard_values "tg-board" as b %}{{ b.cells.0.result.display }}',
        staff,
    )
    assert html.startswith("Tag requests=") and ";7;" in html and "of 1 on target" in html and ";2;" in html


def test_nothing_for_what_the_viewer_may_not_open(staff, rows):
    member = User.objects.create_user("tags-member", password="x")
    assert render('{% goal_list "tg-private" %}', member).strip() == ""
    assert render('{% goal_values "tg-private" as g %}{{ g|default:"none" }}', member) == "none"
    anon = AnonymousUser()
    for tag in ('{% goal_list "tg-goals" %}', '{% card "tg_card" %}', '{% report "tg-report" %}'):
        assert render(tag, anon).strip() == "", tag
    assert render('{% metric_value "tg_requests" as m %}{{ m|default:"none" }}', anon) == "none"
    assert render('{% card "no_such_card" %}', staff).strip() == ""


def test_the_assets_tag_brings_what_custom_markup_needs():
    html = render("{% dashboards_assets %}", AnonymousUser())
    assert "dashboards/css/dashboards.css" in html and "dashboards/js/cards.js" in html
    assert "dashboards/js/about-info.js" in html
