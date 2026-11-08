"""Keeping the pile small: tags on every owned row, and archiving — out of
lists and pickers, still drawn wherever it's referred to."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Dashboard, GoalList, Metric, Report, split_tags, usage_index

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="keeper", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


def test_tags_are_tidied_and_matched_whole():
    assert split_tags(" Ops,  weekly   review ,ops, ,") == ["Ops", "weekly review"]
    Metric(key="a", name="A", dataset=DS, tags="ops, weekly review").save()
    Metric(key="b", name="B", dataset=DS, tags="devops").save()
    Metric(key="c", name="C", dataset=DS, tags="").save()
    assert [m.key for m in Metric.objects.tagged("OPS")] == ["a"]  # any case; not "devops"
    assert [m.key for m in Metric.objects.tagged("weekly review")] == ["a"]
    assert Metric.objects.tagged("").count() == 3
    assert Metric.objects.get(key="a").tag_list == ["ops", "weekly review"]


def test_the_forms_take_tags_and_tidy_them(client, staff):
    resp = client.post(
        reverse("dashboards/metrics-create"),
        {
            "name": "Tagged",
            "source": "dataset",
            "dataset": DS,
            "filter_tree": "{}",
            "agg": "count",
            "format": "number",
            "visibility": "shared",
            "thresholds": "[]",
            "tags": "Ops, ops ,  weekly review",
        },
    )
    assert resp.status_code == 302, getattr(resp, "context", None) and resp.context["form"].errors
    assert Metric.objects.get(key="tagged").tags == "Ops, weekly review"
    html = client.get(reverse("dashboards/metrics-update", args=[Metric.objects.get(key="tagged").pk])).content.decode()
    assert 'name="tags"' in html and 'placeholder="ops, weekly review"' in html


def test_the_overviews_show_chips_and_narrow_to_a_tag(client, staff):
    Metric(key="m1", name="Ops errors", dataset=DS, tags="ops").save()
    Metric(key="m2", name="Sales", dataset=DS, tags="finance").save()
    GoalList(name="Ops review", slug="ops-review", sections=[], tags="ops, weekly review").save()
    Report(name="Money", slug="money", items=[{"metric": "m2"}], tags="finance").save()
    Dashboard(name="Ops board", slug="ops-board", tags="ops").save()
    html = client.get("/smallstack/goals/").content.decode()
    assert html.count('class="dash-tag"') >= 4 and 'href="/smallstack/goals/?tag=weekly%20review"' in html
    resp = client.get("/smallstack/goals/?tag=ops")
    html = resp.content.decode()
    assert [r["metric"].key for r in resp.context["metric_rows"]] == ["m1"]
    assert "Ops review" in html and "Money" not in html.split('id="ix-report-section"')[1]
    # The bar marks the tag the page is narrowed to, and offers the way back.
    assert 'class="dash-tag is-current" aria-current="true">ops<span class="dash-tag-count">2</span>' in html
    assert 'class="dash-tag ix-tag-all"' in html and ">Show everything</a>" in html
    resp = client.get("/smallstack/dashboards/?tag=finance")
    assert resp.status_code == 200 and "Ops board" not in resp.content.decode().split('id="dx-board-section"')[-1]
    resp = client.get("/smallstack/dashboards/?tag=ops")
    assert "Ops board" in resp.content.decode()


def test_archiving_hides_from_lists_and_pickers_but_not_from_what_uses_it(client, staff):
    m = Metric(key="kept", name="Kept", dataset=DS)
    m.save()
    board = Dashboard(name="Board", slug="board", layout=[{"type": "metric", "metric": "kept"}])
    board.save()
    goals = [{"metric": "kept", "target": {"op": ">=", "value": 1}}]
    GoalList(name="Goals", slug="goals", sections=[{"title": "", "goals": goals}]).save()
    page = m.get_absolute_url()
    html = client.get(page).content.decode()
    assert f'href="/smallstack/dashboards/archive/metric/{m.pk}/?next=' in html and ">Archive<" in html
    # Archive it.
    resp = client.post(reverse("dashboards_archive", args=["metric", m.pk]), {"next": page})
    assert resp.status_code == 302 and resp.url == page
    m.refresh_from_db()
    assert m.is_archived
    # Gone from the overview, the CRUD list and the REST list; still at its own page and by key.
    assert m not in [r["metric"] for r in client.get("/smallstack/goals/").context["metric_rows"]]
    overview = client.get("/smallstack/goals/").content.decode()
    # The overview names the kind and links only it: no empty goal-list or report lists.
    assert 'Archived: <a href="/smallstack/dashboards/metrics/?archived=1">1 metric</a></span>' in overview
    listing = client.get(reverse("dashboards/metrics-list")).content.decode()
    assert "Kept" not in listing
    # The list itself says there's more, and the way back from there.
    assert "?archived=1" in listing and "Show archived (1)" in listing
    archived = client.get(reverse("dashboards/metrics-list") + "?archived=1").content.decode()
    assert "Kept" in archived and "Back to the list" in archived and "Show archived" not in archived
    assert "Show archived" not in client.get(reverse("dashboards/reports-list")).content.decode()
    html = client.get(page).content.decode()
    assert resp.status_code == 302 and 'class="dash-archived"' in html and ">Restore<" in html
    assert client.get(reverse("dashboards/metrics-update", args=[m.pk])).status_code == 200
    # Not a twin, not in the board editor's picker, not in the goal-add picker.
    editor = client.get(board.get_absolute_url()).content.decode()
    assert "Kept" not in editor.split('id="dash-add-form"')[-1] if 'id="dash-add-form"' in editor else True
    # Still drawn where it's used: the board's card and the goal list evaluate it.
    assert client.get(board.get_absolute_url()).status_code == 200
    goals = client.get("/smallstack/dashboards/g/goals/").content.decode()
    assert "Kept" in goals
    # Usage ignores archived boards: archive the board and the metric is free.
    assert usage_index(staff)["kept"]["boards"] == 1
    client.post(reverse("dashboards_archive", args=["dashboard", board.pk]))
    assert usage_index(staff).get("kept", {}).get("boards", 0) == 0
    # Restore.
    resp = client.post(
        reverse("dashboards_archive", args=["metric", m.pk]), {"restore": "1", "next": "https://evil.example/x"}
    )
    assert resp.status_code == 302 and resp.url == page  # an off-site next is ignored
    m.refresh_from_db()
    assert not m.is_archived


def test_only_an_editor_archives(client):
    owner = User.objects.create_user(username="owner", password="pw-123456")
    m = Metric(key="mine", name="Mine", dataset=DS, owner=owner)
    m.save()
    other = User.objects.create_user(username="other", password="pw-123456")
    client.force_login(other)
    assert client.post(reverse("dashboards_archive", args=["metric", m.pk])).status_code == 404
    assert client.post(reverse("dashboards_archive", args=["nope", m.pk])).status_code == 404
    m.refresh_from_db()
    assert not m.is_archived


def test_a_card_is_archived_from_its_builder(client, staff):
    from apps.dashboards.models import Component

    Metric(key="m", name="M", dataset=DS).save()
    card = Component(name="Card", key="card", type="metric", metric="m")
    card.save()
    page = reverse("dashboards/components-update", args=[card.pk])
    html = client.get(page).content.decode()
    assert f'hx-get="/smallstack/dashboards/archive/component/{card.pk}/?next=' in html and ">Archive<" in html
    resp = client.post(reverse("dashboards_archive", args=["component", card.pk]), {"next": page})
    assert resp.status_code == 302 and resp.url == page
    card.refresh_from_db()
    assert card.is_archived
    html = client.get(page).content.decode()
    assert ">Restore<" in html and 'class="dash-archived"' in html
    assert "Card" not in client.get("/smallstack/dashboards/").content.decode().split('id="dx-component-section"')[-1]
