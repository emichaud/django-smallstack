"""What a metric means, on hover: a name carries its description as data-about
(about-info.js shows it in a hover box) on the metric library, the Goals overview,
a goal list and its weeks. A card goal's text comes from the card first."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.goals import evaluate_goals
from apps.dashboards.models import Component, GoalList, Metric

pytestmark = pytest.mark.django_db

User = get_user_model()

ABOUT = "Every logged request, including the API."


@pytest.fixture
def staff(client):
    user = User.objects.create_user("about-staff", password="x", is_staff=True, is_superuser=True)
    client.force_login(user)
    return user


@pytest.fixture
def metrics():
    described = Metric(key="ab_requests", name="Requests", description=ABOUT, dataset="smallstack_requests")
    described.save()
    bare = Metric(key="ab_bare", name="Bare", dataset="smallstack_requests")
    bare.save()
    return described, bare


@pytest.fixture
def goal_list(metrics):
    Component(name="Traffic card", type="metric", metric="ab_requests", description="The card's own words.").save()
    g = GoalList(
        name="About review",
        slug="about-review",
        sections=[
            {
                "title": "Traffic",
                "goals": [
                    {"metric": "ab_requests", "target": {"op": ">=", "value": 0}},
                    {"metric": "ab_bare", "target": {"op": ">=", "value": 0}},
                    {"component": "traffic_card", "target": {"op": ">=", "value": 0}},
                ],
            }
        ],
    )
    g.save()
    return g


def test_the_metric_library_names_carry_their_description(client, staff, metrics):
    html = client.get(reverse("dashboards/metrics-list")).content.decode()
    assert f'class="lib-name" data-about="{ABOUT}">Requests</a>' in html
    assert "dashboards/js/about-info.js" in html
    # No description, no hover box: an empty one would only be noise.
    assert 'class="lib-name">Bare</a>' in html


def test_the_goals_overview_lists_metrics_with_their_description(client, staff, metrics):
    html = client.get(reverse("goals_index")).content.decode()
    assert f'class="gx-name" data-about="{ABOUT}">Requests</a>' in html
    assert "dashboards/js/about-info.js" in html


def test_a_goal_row_carries_its_description_a_cards_own_first(rf, staff, goal_list):
    request = rf.get("/")
    request.user = staff
    rows = evaluate_goals(goal_list, request)["rows"]
    assert [r["description"] for r in rows] == [ABOUT, "", "The card's own words."]


def test_the_goal_list_and_its_weeks_carry_descriptions(client, staff, goal_list):
    html = client.get(goal_list.get_absolute_url()).content.decode()
    assert html.count("data-about=") == 2
    assert f'data-about="{ABOUT}"' in html and 'data-about="The card&#x27;s own words."' in html
    url = reverse("dashboards_goal_weeks", kwargs={"slug": goal_list.slug})
    weeks = client.get(url + "?view=grid").content.decode()
    assert f'class="gw-goal-name" data-about="{ABOUT}">' in weeks
    # The week board reads captures; the wording still comes from the list as it is now.
    board = client.get(url).content.decode()
    assert f'data-about="{ABOUT}"' in board
