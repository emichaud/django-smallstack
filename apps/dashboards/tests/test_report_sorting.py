"""The report table: clickable headers sort its rows (server-side, ``?order=``,
the CSV follows), and its columns resize with the framework's table-resize.js."""

from __future__ import annotations

import csv
import io

import pytest
from django.contrib.auth import get_user_model

from apps.activity.models import RequestLog
from apps.dashboards.models import Metric, Report
from apps.dashboards.reports import report_order

pytestmark = pytest.mark.django_db
DS = "smallstack_requests"
URL = "/smallstack/dashboards/r/kpis/"


@pytest.fixture
def staff(client):
    user = get_user_model().objects.create_user("rs-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def report():
    for method, n in (("GET", 3), ("POST", 1), ("DELETE", 2)):
        for _ in range(n):
            RequestLog.objects.create(path="/rs", method=method, status_code=200, response_time_ms=5)
    for key, name, method in (("rs_get", "Gets", "GET"), ("rs_post", "Posts", "POST"), ("rs_del", "Deletes", "DELETE")):
        Metric(
            key=key,
            name=name,
            dataset=DS,
            period_field="timestamp",
            filter_tree={
                "and": [{"field": "path", "op": "=", "value": "/rs"}, {"field": "method", "op": "=", "value": method}]
            },
        ).save()
    r = Report(name="KPIs", slug="kpis", items=[{"metric": "rs_post"}, {"metric": "rs_get"}, {"metric": "rs_del"}])
    r.save()
    return r


def _order(html: str) -> list[str]:
    """The metric rows, top to bottom."""
    return sorted(("Gets", "Posts", "Deletes"), key=lambda name: html.index(f">{name}</a>"))


def test_the_report_keeps_its_own_order_until_a_header_is_clicked(client, staff, report):
    assert _order(client.get(URL).content.decode()) == ["Posts", "Gets", "Deletes"]


def test_sorting_by_metric_and_by_a_value_column(client, staff, report):
    assert _order(client.get(URL + "?order=metric").content.decode()) == ["Deletes", "Gets", "Posts"]
    assert _order(client.get(URL + "?order=-metric").content.decode()) == ["Posts", "Gets", "Deletes"]
    largest = client.get(URL + "?order=-c0").content.decode()
    assert _order(largest) == ["Gets", "Deletes", "Posts"]
    assert 'aria-sort="descending" data-field="c0"' in largest and "Back to the report" in largest
    assert _order(client.get(URL + "?order=c0").content.decode()) == ["Posts", "Deletes", "Gets"]


def test_rows_without_a_number_sort_last_either_way(client, staff, report):
    report.items = [*report.items, {"metric": "rs_post", "label": "Gone"}]
    report.save()
    Report.objects.filter(pk=report.pk).update(items=[*report.items[:3], {"metric": "deleted_metric"}])
    for order in ("c0", "-c0"):
        html = client.get(URL + f"?order={order}").content.decode()
        assert html.index("deleted_metric") > html.index(">Gets</a>")


def test_header_links_start_sensibly_and_flip(client, staff, report):
    html = client.get(URL).content.decode()
    assert 'href="?order=metric"' in html and 'href="?order=-c0"' in html  # A–Z; numbers largest first
    flipped = client.get(URL + "?order=metric").content.decode()
    assert 'href="?order=-metric"' in flipped and 'aria-sort="ascending" data-field="metric"' in flipped


def test_the_csv_follows_the_order_and_a_bad_order_is_ignored(client, staff, report):
    rows = list(csv.reader(io.StringIO(client.get(URL + "?order=-c0&format=csv").content.decode())))
    assert [r[0] for r in rows[1:]] == ["Gets", "Deletes", "Posts"]
    html = client.get(URL + "?order=-c0").content.decode()
    assert html.count('href="?order=-c0&amp;format=csv"') == 2  # the header button and the "Use it" link
    assert 'hx-select-oob="#rp-csv,#rp-print"' in html  # an in-place sort refreshes the header buttons too
    assert report_order("c9", {"columns": [{}]}) == "" and report_order("drop table", {"columns": []}) == ""
    assert _order(client.get(URL + "?order=nonsense").content.decode()) == ["Posts", "Gets", "Deletes"]


def test_the_table_resizes_and_sorts_in_place(client, staff, report):
    html = client.get(URL).content.decode()
    assert 'class="rp-table crud-table" data-table-key="report/kpis:metric,all"' in html
    assert html.count('class="col-resizer" role="separator"') == 2 and 'id="rp-page"' in html
    assert 'hx-select="#rp-page" hx-select-oob="#rp-csv,#rp-print" hx-target="#rp-page"' in html
