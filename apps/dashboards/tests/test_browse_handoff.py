"""The hand-off from the dataset browser: the metric form prefilled from
``?dataset=&filter_tree=&agg=&measure=``, the "then build a card" continuation
to the component builder, and the builder prefilled from ``?metric=``."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Component, Metric
from apps.dashboards.tests.support import own_post

pytestmark = pytest.mark.django_db

User = get_user_model()
CREATE = reverse("dashboards/metrics-create")
CARD = reverse("dashboards/components-create")
TREE = {"and": [{"field": "method", "op": "=", "value": "POST"}, {"field": "status_code", "op": ">=", "value": 400}]}


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="handoff", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def _query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_metric_form_prefills_from_the_browser(client, staff):
    resp = client.get(
        CREATE,
        {
            "dataset": "smallstack_requests",
            "filter_tree": json.dumps(TREE),
            "agg": "avg",
            "measure": "response_time_ms",
        },
    )
    assert resp.status_code == 200
    initial = resp.context["form"].initial
    assert initial["dataset"] == "smallstack_requests" and initial["source"] == "dataset"
    assert initial["filter_tree"] == TREE
    assert initial["agg"] == "avg" and initial["measure"] == "response_time_ms"
    assert initial["name"] == "Requests: Method = POST AND Status code ≥ 400"
    html = resp.content.decode()
    assert "status_code" in html  # the tree is in the hidden field for the editor
    assert resp.context["then_card"] is None and 'name="then"' not in html


def test_metric_form_ignores_what_it_cannot_use(client, staff):
    # An unknown dataset, a tree that doesn't apply, an unknown agg or measure: left out, no error.
    resp = client.get(CREATE, {"dataset": "nope", "filter_tree": json.dumps(TREE), "agg": "avg"})
    assert resp.status_code == 200 and "dataset" not in resp.context["form"].initial
    resp = client.get(
        CREATE,
        {
            "dataset": "smallstack_requests",
            "filter_tree": '{"field": "nope", "op": "=", "value": 1}',
            "agg": "mode",
            "measure": "nope",
        },
    )
    initial = resp.context["form"].initial
    assert initial["dataset"] == "smallstack_requests"
    assert "filter_tree" not in initial and "agg" not in initial and "measure" not in initial
    assert initial["name"] == "Requests"
    # A dataset the person can't read is not prefilled.
    client.logout()
    plain = User.objects.create_user(username="plain", password="pw-123456")
    client.force_login(plain)
    resp = client.get(CREATE, {"dataset": "smallstack_requests"})
    if resp.status_code == 200:
        assert "dataset" not in resp.context["form"].initial


def test_saving_with_then_card_opens_the_component_builder_on_the_new_metric(client, staff):
    resp = client.get(
        CREATE,
        {"dataset": "smallstack_requests", "then": "card", "card_type": "metric_group", "dimension": "method"},
    )
    assert resp.context["then_card"] == {
        "type": "metric_group",
        "label": "Grouped stat",
        "dimension": "method",
        "dimension_label": "Method",
    }
    html = resp.content.decode()
    assert 'name="then" value="card"' in html and 'name="dimension" value="method"' in html
    assert "then build a" in html
    resp = client.post(
        CREATE,
        {
            "name": "Requests kept",
            "source": "dataset",
            "dataset": "smallstack_requests",
            "filter_tree": json.dumps(TREE),
            "agg": "count",
            "format": "number",
            "visibility": "shared",
            "thresholds": "[]",
            "then": "card",
            "card_type": "metric_group",
            "dimension": "method",
        },
    )
    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["form"].errors
    metric = Metric.objects.get(key="requests_kept")
    assert metric.filter_tree == TREE
    assert resp.url.startswith(CARD)
    assert _query(resp.url) == {"metric": "requests_kept", "type": "metric_group", "dimension": "method"}
    # Without the hand-off, the save goes where it always did.
    resp = client.post(
        CREATE,
        {
            "name": "Plain save",
            "source": "dataset",
            "dataset": "smallstack_requests",
            "filter_tree": "{}",
            "agg": "count",
            "format": "number",
            "visibility": "shared",
            "thresholds": "[]",
        },
    )
    assert resp.status_code == 302 and not resp.url.startswith(CARD)
    # An unknown card type is no hand-off.
    resp = client.get(CREATE, {"dataset": "smallstack_requests", "then": "card", "card_type": "nope"})
    assert resp.context["then_card"] is None


def test_component_builder_prefills_from_a_metric(client, staff):
    Metric.objects.create(
        name="Errors", key="errors", dataset="smallstack_requests", agg="count", owner=None
    )
    resp = client.get(CARD, {"metric": "errors", "type": "metric_group", "dimension": "method"})
    assert resp.status_code == 200
    initial = resp.context["form"].initial
    # A split filters a dataset of its own: it starts from the metric's definition, not the metric.
    assert "metric" not in initial and initial["type"] == "metric_group"
    assert initial["dataset"] == "smallstack_requests" and initial["filter_tree"] == {} and initial["agg"] == "count"
    assert initial["options"] == {"dimension": "method"}
    assert initial["name"] == "Errors by Method"
    html = resp.content.decode()
    assert 'value="metric_group" checked' in html
    assert "&quot;dimension&quot;: &quot;method&quot;" in html  # the hidden options JSON the builder reads
    # A single-stat card draws the metric itself, takes no dimension; an unknown column is dropped; the name follows.
    resp = client.get(CARD, {"metric": "errors", "type": "metric", "dimension": "method"})
    initial = resp.context["form"].initial
    assert initial["type"] == "metric" and initial["metric"] == "errors"
    assert "options" not in initial and initial["name"] == "Errors"
    resp = client.get(CARD, {"metric": "errors", "type": "pie", "dimension": "nope"})
    initial = resp.context["form"].initial
    assert initial["options"] == {} and initial["name"] == "Errors" and initial["dataset"] == "smallstack_requests"
    # A metric the person can't see (someone else's personal one; staff see all) is not prefilled.
    other = User.objects.create_user(username="other", password="pw-123456")
    Metric.objects.create(name="Mine", key="mine", dataset="smallstack_requests", agg="count", owner=other)
    client.force_login(User.objects.create_user(username="viewer", password="pw-123456"))
    resp = client.get(CARD, {"metric": "mine"})
    if resp.status_code == 200:
        assert "metric" not in resp.context["form"].initial
    client.force_login(staff)
    # And the whole thing saves as a card with the metric's filter as its own.
    resp = client.post(
        CARD,
        {"name": "Errors by method", "type": "metric_group", **own_post("errors"), "options": '{"dimension":"method"}'},
    )
    assert resp.status_code == 302
    card = Component.objects.get(key="errors_by_method")
    assert card.metric == "" and card.dataset == "smallstack_requests" and card.options["dimension"] == "method"


def test_metric_page_links_to_the_card_builder(client, staff):
    metric = Metric.objects.create(
        name="Errors", key="errors", dataset="smallstack_requests", agg="count", owner=None
    )
    resp = client.get(metric.get_absolute_url())
    assert resp.status_code == 200
    assert f"{CARD}?metric=errors" in resp.content.decode()
