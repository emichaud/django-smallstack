"""Make a metric from the dataset browser without leaving it: the modal form
(MetricQuickView) draws from the browser's hand-off with the number it would
make, saves through the same form as the full page, and then offers what to
do next."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Metric

pytestmark = pytest.mark.django_db

User = get_user_model()
QUICK = reverse("dashboards_metric_quick")
TREE = {"and": [{"field": "method", "op": "=", "value": "POST"}, {"field": "status_code", "op": ">=", "value": 400}]}


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="quick", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_the_form_draws_from_the_handoff_with_the_number_it_would_make(client, staff):
    resp = client.get(
        QUICK,
        {"dataset": "smallstack_requests", "filter_tree": json.dumps(TREE), "agg": "count"},
        HTTP_HX_REQUEST="true",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "<html" not in html  # the modal's body only
    assert 'value="Requests: Method = POST AND Status code ≥ 400"' in html
    assert "of <strong>Requests</strong> where Method = POST AND Status code ≥ 400" in html
    # The first date column is the period column, so weeks and goals work from the start.
    assert '<option value="timestamp" selected>' in html
    # Staff build for everyone: shared by default, with "only me" a click away.
    assert 'value="shared" checked' in html and 'value="personal"' in html
    ctx = resp.context
    assert ctx["preview"]["ok"] and ctx["preview"]["result"]["display"] == "0"
    assert ctx["full_url"].startswith(reverse("dashboards/metrics-create"))
    assert _query(ctx["full_url"])["filter_tree"] == json.dumps(TREE)
    # A changed choice redraws: an average needs a column, and the preview says so.
    resp = client.get(QUICK, {"dataset": "smallstack_requests", "agg": "avg", "period_field": ""})
    assert not resp.context["preview"]["ok"] and any("needs a column" in p for p in resp.context["preview"]["problems"])
    assert resp.context["values"]["period_field"] == ""
    # No usable dataset: nothing to draw.
    assert client.get(QUICK, {"dataset": "nope"}).status_code == 404
    assert client.get(QUICK).status_code == 404


def test_saving_makes_the_metric_and_offers_what_next(client, staff):
    resp = client.post(
        QUICK,
        {
            "dataset": "smallstack_requests",
            "filter_tree": json.dumps(TREE),
            "name": "Client errors",
            "agg": "count",
            "measure": "",
            "period_field": "timestamp",
            "format": "compact",
            "visibility": "shared",
        },
    )
    assert resp.status_code == 200
    metric = Metric.objects.get(key="client_errors")
    assert metric.filter_tree == TREE and metric.period_field == "timestamp" and metric.format == "compact"
    assert metric.owner is None and metric.created_by == staff
    html = resp.content.decode()
    assert "Saved as <strong>Client errors</strong>" in html and "Everyone signed in can see it." in html
    assert metric.get_absolute_url() in html
    assert "Make another from these rows" in html and 'hx-get="' + QUICK in html
    assert _query(resp.context["make_card_url"]) == {"metric": "client_errors"}
    # Personal, and the same name again: the key is made free, the owner set.
    resp = client.post(
        QUICK,
        {"dataset": "smallstack_requests", "name": "Client errors", "agg": "count", "visibility": "personal"},
    )
    assert resp.status_code == 200
    mine = Metric.objects.get(owner=staff)
    assert mine.key != "client_errors" and "Only you can see it." in resp.content.decode()


def test_a_bad_save_redraws_the_form_with_the_problem(client, staff):
    resp = client.post(QUICK, {"dataset": "smallstack_requests", "name": "Avg", "agg": "avg", "measure": ""})
    assert resp.status_code == 422 and not Metric.objects.filter(name="Avg").exists()
    html = resp.content.decode()
    assert "needs a column" in html and 'value="Avg"' in html and "Save metric" in html
    resp = client.post(QUICK, {"dataset": "smallstack_requests", "name": "", "agg": "count"})
    assert resp.status_code == 422 and "required" in resp.content.decode()


def test_then_card_leads_to_the_component_builder(client, staff):
    params = {
        "dataset": "smallstack_requests",
        "agg": "count",
        "then": "card",
        "card_type": "metric_group",
        "dimension": "method",
    }
    html = client.get(QUICK, params).content.decode()
    assert "a <strong>Grouped stat</strong> card is built from it, grouped by <strong>Method</strong>" in html
    assert 'name="card_type" value="metric_group"' in html
    resp = client.post(QUICK, {**params, "name": "By method", "visibility": "shared"})
    assert resp.status_code == 200
    card_url = resp.context["card_url"]
    assert card_url.startswith(reverse("dashboards/components-create"))
    assert _query(card_url) == {"metric": "by_method", "type": "metric_group", "dimension": "method"}
    assert "Build the Grouped stat card" in resp.content.decode()


def test_only_someone_who_can_read_the_dataset_gets_the_form(client):
    plain = User.objects.create_user(username="plain", password="pw-123456")
    client.force_login(plain)
    resp = client.get(QUICK, {"dataset": "smallstack_requests"})
    assert resp.status_code == 404


def test_the_form_says_when_the_metric_already_exists(client, staff):
    Metric.objects.create(name="Client errors", key="client_errors", dataset="smallstack_requests", filter_tree=TREE)
    Metric.objects.create(name="All requests", key="all_requests", dataset="smallstack_requests")
    # The same rows counted the same way: a twin, named, with the way to it.
    resp = client.get(QUICK, {"dataset": "smallstack_requests", "filter_tree": json.dumps(TREE), "agg": "count"})
    html = resp.content.decode()
    assert [m.key for m in resp.context["twins"]] == ["client_errors"]
    assert "You already have this number as" in html and 'href="/smallstack/dashboards/m/client_errors/"' in html
    assert "Save metric" in html  # still allowed — a different name, period or format may be wanted
    # Different rows, or a different number of the same rows: no twin; the others on the dataset are named.
    resp = client.get(
        QUICK,
        {"dataset": "smallstack_requests", "filter_tree": json.dumps(TREE), "agg": "distinct", "measure": "method"},
    )
    assert resp.context["twins"] == [] and resp.context["on_dataset_count"] == 2
    assert "2 other metrics read" in resp.content.decode()
    resp = client.get(QUICK, {"dataset": "smallstack_requests"})
    assert [m.key for m in resp.context["twins"]] == ["all_requests"]
    # Twins are the metrics the person can see: staff see someone else's personal one too.
    other = User.objects.create_user(username="other", password="pw-123456")
    Metric.objects.create(name="Theirs", key="theirs", dataset="smallstack_requests", filter_tree=TREE, owner=other)
    resp = client.get(QUICK, {"dataset": "smallstack_requests", "filter_tree": json.dumps(TREE)})
    assert [m.key for m in resp.context["twins"]] == ["client_errors", "theirs"]
    assert "Client errors</a> and <a" in resp.content.decode()
    # A quick filter carries "500" as text where the editor stored 500: the same condition, so a twin.
    Metric.objects.create(
        name="Server errors", key="server_errors", dataset="smallstack_requests",
        filter_tree={"field": "status_code", "op": ">=", "value": 500},
    )
    typed = {"field": "status_code", "op": ">=", "value": "500"}
    resp = client.get(QUICK, {"dataset": "smallstack_requests", "filter_tree": json.dumps(typed)})
    assert [m.key for m in resp.context["twins"]] == ["server_errors"]
