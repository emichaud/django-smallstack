"""Archive, delete and duplicate each ask first, in the global modal (htmx) or as
a page of its own, and say what the action means: what keeps working, what goes,
what the copy will be."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.dashboards.models import Component, Dashboard, GoalList, Metric, Playlist

pytestmark = pytest.mark.django_db

User = get_user_model()
DS = "smallstack_requests"
HX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def staff(client):
    user = User.objects.create_user(username="confirmer", password="pw-123456", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def used():
    """A metric on a saved card, the card on a dashboard, the dashboard in a
    playlist, and a goal list on that dashboard."""
    Metric(key="req", name="Requests", dataset=DS).save()
    card = Component(name="Req card", key="req_card", type="metric", metric="req")
    card.save()
    goals = GoalList(
        name="Weekly",
        slug="weekly",
        sections=[{"title": "", "goals": [{"metric": "req", "target": {"op": ">=", "value": 1}}]}],
    )
    goals.save()
    board = Dashboard(
        name="Ops board",
        slug="ops-board",
        layout=[
            {"id": "a", "type": "metric", "component": "req_card", "x": 0, "y": 0, "w": 3, "h": 2},
            {"id": "b", "type": "goals", "options": {"goal_list": "weekly"}, "x": 3, "y": 0, "w": 6, "h": 4},
        ],
    )
    board.save()
    playlist = Playlist(name="Wall", slug="wall", items=[{"dashboard": "ops-board"}, {"goals": "weekly"}])
    playlist.save()
    return {"card": card, "board": board, "goals": goals, "playlist": playlist}


def test_archive_asks_first_and_says_what_keeps_working(client, staff, used):
    card = used["card"]
    url = reverse("dashboards_archive", args=["component", card.pk])
    modal = client.get(url + "?next=/smallstack/dashboards/", **HX).content.decode()
    assert "<html" not in modal and "isn't deleted" in modal
    assert "Still used by" in modal and "Ops board" in modal
    assert 'name="next" value="/smallstack/dashboards/"' in modal and "Show archived" in modal
    card.refresh_from_db()
    assert not card.is_archived  # asking changes nothing
    page = client.get(url).content.decode()
    assert "<html" in page and "Archive Req card?" in page
    # An off-site next falls back to the row's own page.
    assert (
        f'value="{card.get_absolute_url()}"' in client.get(url + "?next=https://evil.example/", **HX).content.decode()
    )


def test_the_new_delete_confirmations_say_what_goes(client, staff, used):
    card = client.get(reverse("dashboards/components-delete", args=[used["card"].pk]), **HX).content.decode()
    assert "<html" not in card and "Placed on" in card and "as a card of its own" in card and "Archive" in card
    playlist = client.get(reverse("dashboards/playlists-delete", args=[used["playlist"].pk]), **HX).content.decode()
    assert "its 2 slides" in playlist and "stay as they are" in playlist
    goals = client.get(reverse("dashboards/goals-delete", args=[used["goals"].pk]), **HX).content.decode()
    assert "Shown on" in goals and "Ops board" in goals and "Wall" in goals and "The metrics it judges stay" in goals
    # Without htmx, the same body on a page of its own.
    page = client.get(reverse("dashboards/goals-delete", args=[used["goals"].pk])).content.decode()
    assert "<html" in page and "Delete Weekly?" in page and "can't be undone" in page


def test_the_library_trash_icons_open_the_modal(client, staff, used):
    for url_name in ("dashboards/components-list", "dashboards/goals-list", "dashboards/playlists-list"):
        html = client.get(reverse(url_name)).content.decode()
        assert 'data-stat-modal="Delete ' in html, url_name


def test_duplicate_needs_only_view_and_archive_needs_edit(client, used):
    viewer = User.objects.create_user(username="viewer", password="pw-123456")
    client.force_login(viewer)
    board = used["board"]
    assert client.get(reverse("dashboards_duplicate", args=["dashboard", board.pk]), **HX).status_code == 200
    assert client.get(reverse("dashboards_archive", args=["dashboard", board.pk]), **HX).status_code == 404
    assert client.get(reverse("dashboards_duplicate", args=["nope", board.pk])).status_code == 404
