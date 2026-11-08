"""Duplicate: the create form opened with an existing metric's or card's
settings (``?from=<key>``), nothing saved until Save. The copy starts
personal, named "(copy)", and gets its own key from its name."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Component, Metric
from apps.dashboards.tests.support import own, own_post

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
TREE = {"field": "status_code", "op": ">=", "value": 500}


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="dup", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def test_a_metric_duplicates_into_a_prefilled_form_and_saves_as_its_own_row(client, staff):
    original = Metric(
        key="server_errors",
        name="Server errors",
        description="5xx",
        dataset=DS,
        filter_tree=TREE,
        period_field="timestamp",
        format="compact",
        thresholds=[{"op": ">=", "value": 10, "state": "danger"}],
        tags="ops",
    )
    original.save()
    page = client.get(original.get_absolute_url()).content.decode()
    confirm = reverse("dashboards_duplicate", args=["metric", original.pk])
    assert f'hx-get="{confirm}"' in page and ">Duplicate<" in page
    # The confirmation says what the copy will be, then opens the form.
    note = client.get(confirm, HTTP_HX_REQUEST="true").content.decode()
    assert f'href="{reverse("dashboards/metrics-create")}?from=server_errors"' in note
    assert "Server errors (copy)" in note and "starts personal" in note and "<html" not in note
    resp = client.get(reverse("dashboards/metrics-create"), {"from": "server_errors"})
    assert resp.status_code == 200
    initial = resp.context["form"].initial
    assert initial["name"] == "Server errors (copy)" and "key" not in initial
    assert initial["filter_tree"] == TREE and initial["thresholds"] == original.thresholds
    assert initial["period_field"] == "timestamp" and initial["format"] == "compact" and initial["tags"] == "ops"
    assert initial["visibility"] == "personal"
    # Saved: a second row, its own key, personal to the person, the original untouched.
    resp = client.post(
        reverse("dashboards/metrics-create"),
        {
            "name": "Server errors, weekly",
            "source": "dataset",
            "dataset": DS,
            "filter_tree": '{"field": "status_code", "op": ">=", "value": 500}',
            "agg": "count",
            "period_field": "timestamp",
            "format": "compact",
            "thresholds": "[]",
            "tags": "ops",
            "visibility": "personal",
        },
    )
    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["form"].errors
    copy = Metric.objects.get(key="server_errors_weekly")
    assert copy.owner == staff and copy.filter_tree == TREE
    original.refresh_from_db()
    assert original.name == "Server errors" and original.owner is None and Metric.objects.count() == 2
    # An unknown or unviewable original: the plain form.
    plain = client.get(reverse("dashboards/metrics-create"), {"from": "nope"})
    assert "filter_tree" not in plain.context["form"].initial


def test_a_card_duplicates_from_its_builder(client, staff):
    Metric(key="m", name="M", dataset=DS).save()
    card = Component(
        name="M by method",
        key="m_by_method",
        type="metric_group",
        **own("m"),
        options={"dimension": "method"},
        tags="ops",
    )
    card.save()
    page = client.get(reverse("dashboards/components-update", args=[card.pk])).content.decode()
    confirm = reverse("dashboards_duplicate", args=["component", card.pk])
    assert f'hx-get="{confirm}"' in page and ">Duplicate<" in page
    note = client.get(confirm).content.decode()  # without htmx: a page of its own
    assert f'href="{reverse("dashboards/components-create")}?from=m_by_method"' in note and "<html" in note
    resp = client.get(reverse("dashboards/components-create"), {"from": "m_by_method"})
    initial = resp.context["form"].initial
    assert initial["name"] == "M by method (copy)" and initial["type"] == "metric_group"
    assert initial["dataset"] == DS and initial["metric"] == ""  # its own source comes along
    assert initial["options"] == {"dimension": "method"} and initial["tags"] == "ops"
    assert initial["visibility"] == "personal"
    resp = client.post(
        reverse("dashboards/components-create"),
        {"name": "M by path", "type": "metric_group", **own_post("m"), "options": '{"dimension": "path"}', "tags": "x"},
    )
    assert resp.status_code == 302
    copy = Component.objects.get(key="m_by_path")
    assert copy.options["dimension"] == "path" and Component.objects.count() == 2


def test_someone_who_cannot_see_the_original_gets_the_plain_form(client):
    owner = User.objects.create_user(username="owner", password="pw-123456")
    Metric(key="private", name="Private", dataset=DS, owner=owner).save()
    client.force_login(User.objects.create_user(username="other", password="pw-123456"))
    resp = client.get(reverse("dashboards/metrics-create"), {"from": "private"})
    if resp.status_code == 200:
        assert "dataset" not in resp.context["form"].initial


@pytest.mark.parametrize(
    "model, url_base, page_name, carried",
    [
        (
            "Dashboard",
            "boards",
            "dashboards_dashboard",
            {"layout": [{"type": "metric", "metric": "m"}], "refresh_seconds": 60},
        ),
        ("Report", "reports", "dashboards_report", {"items": [{"metric": "m"}], "periods": ["mtd", "pmtd"]}),
        ("Playlist", "playlists", "dashboards_playlist", {"items": [], "seconds": 20, "loop": False}),
        (
            "GoalList",
            "goals",
            "dashboards_goals",
            {"sections": [{"title": "S", "goals": [{"metric": "m", "target": {"op": ">=", "value": 1}}]}]},
        ),
    ],
)
def test_the_slug_keyed_types_duplicate_the_same_way(client, staff, model, url_base, page_name, carried):
    from apps.dashboards import models as m

    Metric(key="m", name="M", dataset=DS).save()
    cls = getattr(m, model)
    original = cls(name="Original", slug="original", tags="ops", **carried)
    original.save()
    create = reverse(f"dashboards/{url_base}-create")
    page = client.get(reverse(page_name, args=["original"])).content.decode()
    kind = {"Dashboard": "dashboard", "Report": "report", "Playlist": "playlist", "GoalList": "goals"}[model]
    confirm = reverse("dashboards_duplicate", args=[kind, original.pk])
    assert f'hx-get="{confirm}"' in page and ">Duplicate<" in page
    assert f'href="{create}?from=original"' in client.get(confirm, HTTP_HX_REQUEST="true").content.decode()
    initial = client.get(create, {"from": "original"}).context["form"].initial
    assert initial["name"] == "Original (copy)" and initial["slug"] == "original-copy" and initial["tags"] == "ops"
    # Compared with the saved row: a goal list's sections are normalised on save (ids added).
    assert initial["visibility"] == "personal" and all(initial[k] == getattr(original, k) for k in carried)
    # A second duplicate gets the next free slug.
    cls(name="Original (copy)", slug="original-copy", **carried).save()
    assert client.get(create, {"from": "original"}).context["form"].initial["slug"] == "original-copy-2"
    assert "slug" not in client.get(create, {"from": "nope"}).context["form"].initial
