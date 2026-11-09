"""Start from a saved metric on the dataset browser: the metrics already made on
a dataset are listed there; picking one loads its conditions and roll-up, and
Make a metric is then a copy of it, with the conditions as they are now."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Metric

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
BROWSE = reverse("datasets:browse", args=[DS])
QUICK = reverse("dashboards_metric_quick")
TREE = {"field": "status_code", "op": ">=", "value": 500}


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="starter", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def errors():
    m = Metric(
        key="srv_errors",
        name="Server errors",
        description="5xx answers.",
        dataset=DS,
        filter_tree=TREE,
        period_field="timestamp",
        format="compact",
        unit="req",
        tags="ops",
        thresholds=[{"op": ">", "value": 0, "state": "danger"}],
    )
    m.save()
    return m


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_the_browser_lists_the_metrics_on_this_dataset(client, staff, errors):
    Metric(key="slow", name="Slow requests", dataset=DS, agg="avg", measure="response_time_ms").save()
    Metric(key="other", name="On another dataset", dataset="smallstack_heartbeats").save()
    put_away = Metric(key="gone", name="Archived one", dataset=DS)
    put_away.save()
    put_away.set_archived(True)
    resp = client.get(BROWSE)
    saved = {m["key"]: m for m in resp.context["saved_metrics"]}
    assert set(saved) == {"srv_errors", "slow"}  # this dataset's, not archived ones
    errors_query = _query(saved["srv_errors"]["url"])
    # Compared as JSON, not as a string: Postgres's jsonb doesn't keep key order.
    assert json.loads(errors_query.pop("filter_tree")) == TREE
    assert errors_query == {"metric": "srv_errors"}
    # A measure's roll-up comes along too.
    assert _query(saved["slow"]["url"]) == {"metric": "slow", "measure": "response_time_ms", "agg": "avg"}
    html = resp.content.decode()
    assert "Start from a metric" in html and resp.context["loaded_metric"] is None


def test_a_loaded_metric_makes_a_copy(client, staff, errors):
    url = next(m["url"] for m in client.get(BROWSE).context["saved_metrics"] if m["key"] == "srv_errors")
    resp = client.get(url)
    assert resp.context["loaded_metric"] == errors
    html = resp.content.decode()
    assert 'name="metric" value="srv_errors"' in html  # kept as the filters change
    assert 'data-stat-modal="Make a copy of Server errors"' in html
    assert "Server errors</a>'s conditions" in html and "Server errors itself doesn't change" in html
    handoff = _query(resp.context["metric_url"])
    assert handoff["from"] == "srv_errors" and handoff["name"] == "Server errors (copy)"
    assert handoff["period_field"] == "timestamp" and handoff["format"] == "compact"
    assert json.loads(handoff["filter_tree"]) == TREE


def test_without_javascript_a_pick_loads_the_same_address(client, staff, errors):
    resp = client.get(BROWSE, {"metric": "srv_errors"})
    assert resp.status_code == 302 and json.loads(_query(resp.url)["filter_tree"]) == TREE
    assert client.get(BROWSE, {"metric": ""}).status_code == 200  # "start over"
    assert client.get(BROWSE, {"metric": "nope"}).status_code == 200


def test_saving_the_copy_carries_the_rest_and_leaves_the_original(client, staff, errors):
    changed = {"and": [TREE, {"field": "method", "op": "=", "value": "POST"}]}
    params = {
        "dataset": DS,
        "filter_tree": json.dumps(changed),
        "agg": "count",
        "from": "srv_errors",
        "name": "Server errors (copy)",
        "period_field": "timestamp",
        "format": "compact",
    }
    form = client.get(QUICK, params, HTTP_HX_REQUEST="true").content.decode()
    assert 'name="from" value="srv_errors"' in form and "A copy of" in form
    resp = client.post(QUICK, {**params, "name": "POST server errors", "visibility": "shared"})
    assert resp.status_code == 200, resp.content.decode()[:500]
    copy = Metric.objects.get(name="POST server errors")
    assert copy.pk != errors.pk and copy.key != "srv_errors"
    assert copy.filter_tree == changed and copy.format == "compact" and copy.period_field == "timestamp"
    assert (copy.unit, copy.description, copy.tags) == ("req", "5xx answers.", "ops")
    assert copy.thresholds == errors.thresholds
    errors.refresh_from_db()
    assert errors.filter_tree == TREE and errors.name == "Server errors"


def test_a_copy_of_a_metric_on_another_dataset_is_not_a_copy(client, staff):
    Metric(key="hb", name="Heartbeats", dataset="smallstack_heartbeats", unit="x").save()
    resp = client.get(QUICK, {"dataset": DS, "agg": "count", "from": "hb"}, HTTP_HX_REQUEST="true")
    assert resp.context["copy_of"] is None and 'name="from"' not in resp.content.decode()


def test_the_full_form_keeps_the_browsers_conditions_over_the_copy(client, staff, errors):
    changed = {"and": [TREE, {"field": "method", "op": "=", "value": "POST"}]}
    params = {"dataset": DS, "filter_tree": json.dumps(changed), "agg": "count", "from": "srv_errors"}
    full = client.get(QUICK, params, HTTP_HX_REQUEST="true").context["full_url"]
    initial = client.get(full).context["form"].initial
    assert initial["filter_tree"] == changed and initial["name"] == "Server errors (copy)"
    assert initial["thresholds"] == errors.thresholds and initial["unit"] == "req"
    # A plain Duplicate (no browser hand-off) still copies the original's own conditions.
    plain = client.get(reverse("dashboards/metrics-create"), {"from": "srv_errors"}).context["form"].initial
    assert plain["filter_tree"] == TREE
