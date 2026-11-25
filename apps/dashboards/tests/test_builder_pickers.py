"""The component builder's pickers: datasets grouped as the app's own, then
SmallStack's; metrics grouped Personal and Shared; the source as choice tiles."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.forms import grouped_dataset_choices
from apps.dashboards.models import Metric

pytestmark = pytest.mark.django_db

User = get_user_model()
CARD = reverse("dashboards/components-create")


def test_app_datasets_come_before_the_system_ones() -> None:
    choices = grouped_dataset_choices(
        [("smallstack_requests", "Requests"), ("lions_seasons", "Lions seasons"), ("smallstack_users", "Users")]
    )
    assert choices == [
        ("This app's data", [("lions_seasons", "Lions seasons")]),
        ("SmallStack system data", [("smallstack_requests", "Requests"), ("smallstack_users", "Users")]),
    ]


def test_one_kind_of_dataset_stays_a_flat_list() -> None:
    only_system = [("smallstack_requests", "Requests"), ("smallstack_users", "Users")]
    assert grouped_dataset_choices(only_system) == only_system
    assert grouped_dataset_choices([("lions_seasons", "Lions seasons")]) == [("lions_seasons", "Lions seasons")]


def test_metrics_are_grouped_personal_then_shared_and_the_source_is_tiles(client) -> None:
    user = User.objects.create_user("bp-staff", password="x", is_staff=True)
    client.force_login(user)
    Metric(key="bp_shared", name="Shared one", dataset="smallstack_requests").save()
    Metric(key="bp_mine", name="Mine", dataset="smallstack_requests", owner=user).save()

    html = client.get(CARD).content.decode()

    metric_select = html.split('id="cb-metric"', 1)[1].split("</select>", 1)[0]
    personal = metric_select.index('<optgroup label="Personal">')
    shared = metric_select.index('<optgroup label="Shared">')
    assert personal < metric_select.index('value="bp_mine"') < shared < metric_select.index('value="bp_shared"')
    # The source switch: choice tiles over the same cb_source radios the script reads.
    assert 'class="df-choice-cards cb-source-pick"' in html
    assert html.count('name="cb_source"') == 2


def test_no_empty_personal_group(client) -> None:
    client.force_login(User.objects.create_user("bp-staff2", password="x", is_staff=True))
    Metric(key="bp_only_shared", name="Shared one", dataset="smallstack_requests").save()

    html = client.get(CARD).content.decode()

    assert '<optgroup label="Personal">' not in html and '<optgroup label="Shared">' in html
