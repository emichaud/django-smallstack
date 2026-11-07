"""The two new charts, and the components page drawing the real cards."""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.activity.models import RequestLog
from apps.dashboards.boards import render_cell
from apps.dashboards.metrics import request_for
from apps.dashboards.models import Component, Dashboard, Metric
from apps.dashboards.tests.support import own

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff():
    return User.objects.create_user("cp-staff", password="x", is_staff=True)


@pytest.fixture
def requests_metric():
    for method, n in (("GET", 6), ("POST", 3), ("PUT", 1)):
        for _ in range(n):
            RequestLog.objects.create(path="/x", method=method, status_code=200, response_time_ms=10)
    m = Metric(key="reqs", name="Requests", dataset="smallstack_requests", period_field="timestamp")
    m.save()
    return m


def draw(kind, metric, user, **options):
    # A chart filters a dataset of its own: the metric's definition, as the card's.
    cell = {"id": "c", "type": kind, **own(metric.key), "options": {"dimension": "method", **options}}
    return render_cell(Dashboard(name="B", slug="b"), cell, request_for(user), None)


def test_a_pie_shows_each_groups_share(staff, requests_metric):
    html = draw("pie", requests_metric, staff)
    assert "<svg" in html and "60%" in html and "30%" in html and "10%" in html
    assert html.count('pathLength="100"') == 3
    assert 'stroke-dasharray="60.00 40.00"' in html
    assert "dashboards/preview-rows/?narrow=" in html  # each group opens its rows (an unsaved board: the preview route)


def test_slices_add_up_and_start_where_the_last_ended(staff, requests_metric):
    html = draw("pie", requests_metric, staff)
    assert re.findall(r'stroke-dashoffset="([\d.-]+)"', html) == ["25.00", "-35.00", "-65.00"]


def test_a_pie_of_an_average_says_why_not(staff):
    m = Metric(key="avg", name="Avg", dataset="smallstack_requests", agg="avg", measure="response_time_ms")
    m.save()
    html = draw("pie", m, staff)
    assert "<svg" not in html and "needs a count or a sum" in html


def test_a_pie_with_nothing_to_show_says_so(staff, requests_metric):
    RequestLog.objects.all().delete()
    html = draw("pie", requests_metric, staff)
    assert "pathLength" not in html and "Nothing to show" in html


def test_ranked_bars_run_largest_first_and_take_any_aggregation(staff, requests_metric):
    html = draw("ranked", requests_metric, staff)
    assert "--share: 1.0000" in html and "--share: 0.5000" in html
    assert html.index(">GET<") < html.index(">POST<") < html.index(">PUT<")
    m = Metric(key="avg", name="Avg", dataset="smallstack_requests", agg="avg", measure="response_time_ms")
    m.save()
    assert "ranked-bar" in draw("ranked", m, staff)


def test_restricted_data_stays_hidden_in_both(requests_metric):
    member = User.objects.create_user("cp-member", password="x")
    for kind in ("pie", "ranked"):
        html = draw(kind, requests_metric, member)
        assert "Restricted" in html or "access" in html
        assert "60%" not in html and "--share" not in html


def test_the_builder_offers_them_only_with_a_column_to_group_by(staff, requests_metric):
    from apps.dashboards.components import describe_types

    types = {t["type"]: t for t in describe_types(staff)}
    assert types["pie"]["group"] == "Charts" and types["ranked"]["group"] == "Charts"
    assert types["pie"]["requires"] == ["dimension"] == types["ranked"]["requires"]


def test_a_card_cant_save_without_a_column(requests_metric):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        Component(name="Bad", type="pie", **own("reqs"), options={}).save()


class TestThePage:
    @pytest.fixture
    def card(self, requests_metric):
        c = Component(name="By method", type="ranked", **own("reqs"), options={"dimension": "method"})
        c.save()
        return c

    def test_the_preview_draws_the_real_card(self, client, staff, card):
        client.force_login(staff)
        html = client.get(reverse("dashboards_component_preview", kwargs={"pk": card.pk})).content.decode()
        assert "ranked-bar" in html and "GET" in html

    def test_someone_elses_personal_card_is_404(self, client, requests_metric):
        owner = User.objects.create_user("cp-owner", password="x", is_staff=True)
        Metric(key="own", name="Own", source="manual", owner=owner).save()
        mine = Component(name="Mine", type="metric", metric="own", owner=owner)
        mine.save()
        client.force_login(User.objects.create_user("cp-member", password="x"))
        assert client.get(reverse("dashboards_component_preview", kwargs={"pk": mine.pk})).status_code == 404

    def test_a_viewer_who_cant_read_the_data_sees_restricted(self, client, card):
        client.force_login(User.objects.create_user("cp-member", password="x"))
        html = client.get(reverse("dashboards_component_preview", kwargs={"pk": card.pk})).content.decode()
        assert "ranked-bar" not in html

    def test_login_is_required(self, client, card):
        assert client.get(reverse("dashboards_component_preview", kwargs={"pk": card.pk})).status_code == 302

    def test_the_list_rows_carry_their_preview(self, client, staff, card):
        client.force_login(staff)
        html = client.get(reverse("dashboards/components-list"), {"display": "library"}).content.decode()
        assert f'data-preview-url="{reverse("dashboards_component_preview", kwargs={"pk": card.pk})}"' in html
        assert "component-list.js" in html and 'id="cl-peek"' in html

    def test_the_gallery_loads_each_card_lazily_and_inert(self, client, staff, card):
        client.force_login(staff)
        html = client.get(reverse("dashboards/components-list")).content.decode()  # the gallery is the default
        assert 'class="cc-grid"' in html and 'hx-trigger="revealed"' in html and " inert " in html
        assert "ranked-bar" not in html  # nothing evaluated up front
        assert "website/css/dashboard-cards.css" in html

    def test_the_gallery_pages_like_the_table(self, client, staff, card):
        for i in range(16):
            Component(name=f"Paged {i:02d}", type="ranked", **own("reqs"), options={"dimension": "method"}).save()
        client.force_login(staff)
        url = reverse("dashboards/components-list")
        html = client.get(url).content.decode()
        assert html.count('<li class="cc-card">') == 15 and "Showing 1&ndash;15 of 17" in html
        assert 'hx-target="#crud-display-area"' in html and '<option value="15" selected>' in html
        assert client.get(url, {"page": 2}).content.decode().count('<li class="cc-card">') == 2
        wide = client.get(url, {"per_page": 25}).content.decode()
        assert wide.count('<li class="cc-card">') == 17 and 'name="per_page"' in wide  # one page, control kept
