"""The print documents: the same numbers as the pages, in a form for paper."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.dashboards.entries import record_entry
from apps.dashboards.models import GoalList, Metric, Report
from apps.dashboards.weeks import take_snapshot, week_of

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("pr-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def metric(staff):
    m = Metric(key="csat", name="CSAT", source="manual", agg="sum")
    m.save()
    record_entry(m, timezone.localdate(), Decimal(80), by=staff)
    return m


def goals(metric, **extra):
    g = GoalList(
        name="Ops review",
        slug="ops",
        description="The Monday meeting",
        sections=[
            {
                "title": "Service",
                "goals": [
                    {"id": "a", "metric": metric.key, "target": {"op": ">=", "value": 90}, "note": "From the survey"}
                ],
            }
        ],
        **extra,
    )
    g.save()
    return g


def report(metric, *periods):
    r = Report(name="Monthly", slug="monthly", items=[{"metric": metric.key}], periods=list(periods))
    r.save()
    return r


def test_goal_list_document(client, metric):
    html = client.get(reverse("dashboards_goals_print", kwargs={"slug": goals(metric).slug})).content.decode()
    for text in ("Ops review", "The Monday meeting", "Service", "CSAT", "From the survey", "Needs attention"):
        assert text in html
    assert "80" in html and "≥ 90" in html
    assert "Missed" in html  # status is a word: a printer may have no colour


def test_it_has_no_site_menus_and_no_inline_script(client, metric):
    html = client.get(reverse("dashboards_goals_print", kwargs={"slug": goals(metric).slug})).content.decode()
    assert "sidebar" not in html
    assert 'data-theme="light"' in html
    assert "<script>" not in html and "onclick" not in html


def test_the_dialog_opens_only_when_asked(client, metric):
    url = reverse("dashboards_goals_print", kwargs={"slug": goals(metric).slug})
    assert "data-auto-print" not in client.get(url).content.decode()
    assert "data-auto-print" in client.get(url + "?auto=1").content.decode()


def test_it_follows_the_period_on_screen(client, staff):
    m = Metric(key="spend", name="Spend", source="manual", agg="sum")
    m.save()
    record_entry(m, timezone.localdate() - timedelta(days=400), Decimal(7777), by=staff)
    url = reverse("dashboards_goals_print", kwargs={"slug": goals(m).slug})
    assert "7,777" in client.get(url + "?period=all").content.decode()
    assert "7,777" not in client.get(url + "?period=last_30").content.decode()


def test_a_week_prints_its_saved_values(client, staff, metric):
    g = goals(metric, created_by=staff)
    week = week_of(timezone.localdate()) - timedelta(weeks=1)
    record_entry(metric, week, Decimal(55), by=staff)
    take_snapshot(g, week)
    html = client.get(
        reverse("dashboards_goals_print", kwargs={"slug": g.slug}) + f"?week={week.isoformat()}"
    ).content.decode()
    assert "Week of" in html and ">55<" in html.replace(" ", "")


def test_someone_who_cant_see_the_list_cant_print_it(client, metric):
    owner = get_user_model().objects.create_user("pr-owner", password="x")
    g = goals(metric, owner=owner)
    other = get_user_model().objects.create_user("pr-other", password="x")
    client.force_login(other)
    assert client.get(reverse("dashboards_goals_print", kwargs={"slug": g.slug})).status_code == 404


def test_login_is_required(metric):
    from django.test import Client

    assert Client().get(reverse("dashboards_goals_print", kwargs={"slug": goals(metric).slug})).status_code == 302


def test_report_document(client, metric):
    r = report(metric, "mtd", "pmtd")
    html = client.get(reverse("dashboards_report_print", kwargs={"slug": r.slug})).content.decode()
    assert "Monthly" in html and "CSAT" in html and "80" in html and "doc--wide" not in html


def test_a_wide_report_prints_sideways(client, metric):
    r = report(metric, "mtd", "pmtd", "last_30", "last_90")
    assert "doc--wide" in client.get(reverse("dashboards_report_print", kwargs={"slug": r.slug})).content.decode()


def test_the_pages_offer_it(client, metric):
    g = goals(metric)
    assert (
        reverse("dashboards_goals_print", kwargs={"slug": g.slug})
        in client.get(g.get_absolute_url() + "?period=mtd").content.decode()
    )
    r = report(metric, "mtd")
    assert (
        reverse("dashboards_report_print", kwargs={"slug": r.slug}) in client.get(r.get_absolute_url()).content.decode()
    )


def test_a_restricted_number_stays_hidden_on_paper(client, staff):
    member = get_user_model().objects.create_user("pr-member", password="x")
    m = Metric(key="req", name="Requests", dataset="smallstack_requests", period_field="timestamp")
    m.save()
    client.force_login(member)
    html = client.get(reverse("dashboards_goals_print", kwargs={"slug": goals(m).slug})).content.decode()
    assert "Restricted" in html
