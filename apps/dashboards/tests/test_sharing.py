"""Sharing a personal dashboard: with everyone who can sign in, or with people
by name. The owner keeps editing it; whoever it's shared with opens it and
reads its cards as the owner does, except data their own access doesn't reach."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.dashboards.boards import set_sharing
from apps.dashboards.models import Dashboard, Metric
from apps.dashboards.tests.test_dashboards import DS_AUTH, DS_STAFF, _call, _seed
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def alice():
    return User.objects.create_user("alice", password="x", first_name="Alice", last_name="Ames")


@pytest.fixture
def bob():
    return User.objects.create_user("bob", password="x", first_name="Bob")


@pytest.fixture
def carol():
    return User.objects.create_user("carol", password="x")


@pytest.fixture
def board(alice):
    """Alice's personal dashboard over her personal metric (members may read the data)."""
    _seed()
    Metric(key="sh_req", name="Requests", dataset=DS_AUTH, owner=alice, period_field="timestamp").save()
    d = Dashboard(
        name="Alice ops",
        slug="alice-ops",
        owner=alice,
        layout=[{"id": "c1", "type": "metric", "metric": "sh_req"}],
    )
    d.save()
    return d


def test_a_personal_dashboard_is_the_owners_until_shared(board, alice, bob, carol):
    assert board.can_view(alice) and board.can_edit(alice)
    assert not board.can_view(bob) and not board.shared_with_user(bob)
    assert Dashboard.objects.visible_to(bob).count() == 0 and board.audience() == "Personal"

    out = set_sharing(board, actor=alice, add=["bob"])
    assert out["people"] == [{"username": "bob", "name": "Bob"}] and out["added"] == ["bob"]
    board.refresh_from_db()
    assert board.can_view(bob) and not board.can_edit(bob) and board.shared_with_user(bob)
    assert not board.can_view(carol)
    assert list(Dashboard.objects.visible_to(bob)) == [board] and list(Dashboard.objects.shared_with_me(bob)) == [board]
    assert Dashboard.objects.shared_with_me(alice).count() == 0  # never one's own
    assert board.audience() == "Shared with 1 person" and board.audience(bob) == "Shared by alice"
    # A bell for Bob, with the link; none for the owner.
    note = Notification.objects.get(recipient=bob)
    assert "Alice Ames shared a dashboard with you: Alice ops" in note.title and note.url == board.get_absolute_url()
    assert not Notification.objects.filter(recipient=alice).exists()

    set_sharing(board, actor=alice, everyone=True, remove=["bob"])
    board.refresh_from_db()
    assert board.shared_with_everyone and board.can_view(carol) and board.can_view(bob)
    assert board.audience() == "Shared with everyone" and board.sharing == {"everyone": True, "people": []}
    assert Notification.objects.count() == 1  # "everyone" doesn't ring every bell

    set_sharing(board, actor=alice, everyone=False)
    board.refresh_from_db()
    assert not board.can_view(bob) and board.audience() == "Personal"
    # Adding the owner, a stranger or an inactive account does nothing.
    User.objects.create_user("gone", password="x", is_active=False)
    assert set_sharing(board, actor=alice, add=["alice", "nobody", "gone"])["people"] == []


def test_an_ownerless_dashboard_has_nothing_to_share(alice):
    d = Dashboard(name="Everyone's", slug="all", layout=[])
    d.save()
    assert "error" in set_sharing(d, actor=alice, add=["alice"]) and d.audience() == "Shared"


def test_the_share_dialog(client, board, alice, bob, carol):
    client.force_login(alice)
    url = "/smallstack/dashboards/d/alice-ops/share/"
    assert client.get(url).status_code == 302  # the dialog is a fragment: without htmx, back to the dashboard
    html = client.get(url, HTTP_HX_REQUEST="true").content.decode()
    assert 'id="share-dialog"' in html and 'name="everyone"' in html and "Not shared with anyone by name yet" in html
    assert 'id="dash-audience" hx-swap-oob="innerHTML">Personal<' in html  # the header badge follows

    # A member finds people by exact username only (any case); part of a name lists no one.
    assert 'value="bob"' not in client.get(f"{url}?q=bo", HTTP_HX_REQUEST="true").content.decode()
    found = client.get(f"{url}?q=Bob", HTTP_HX_REQUEST="true").content.decode()
    assert 'name="add" value="bob"' in found and "carol" not in found
    html = client.post(url, {"add": "bob", "q": "bo"}, HTTP_HX_REQUEST="true").content.decode()
    assert 'name="remove" value="bob"' in html and "Shared with 1 person<" in html
    assert 'value="bob"' not in html.split('id="share-matches"')[1]  # the search stays; Bob left its matches
    html = client.post(url, {"everyone_sent": "1", "everyone": "1"}, HTTP_HX_REQUEST="true").content.decode()
    assert 'name="everyone" value="1" checked' in html and "Shared with everyone<" in html
    html = client.post(url, {"everyone_sent": "1", "remove": "bob"}, HTTP_HX_REQUEST="true").content.decode()
    assert 'name="remove" value="bob"' not in html and "Personal<" in html

    page = client.get("/smallstack/dashboards/d/alice-ops/").content.decode()
    assert 'id="dash-share"' in page and 'id="dash-audience">Personal<' in page
    # Not the owner's: no dialog, no button.
    client.force_login(bob)
    assert client.get(url, HTTP_HX_REQUEST="true").status_code == 404  # not even visible
    set_sharing(board, actor=alice, add=["bob"])
    assert client.get(url, HTTP_HX_REQUEST="true").status_code == 403
    page = client.get("/smallstack/dashboards/d/alice-ops/").content.decode()
    assert 'id="dash-share"' not in page and 'id="dash-audience">Shared by alice<' in page


def test_a_viewer_reads_the_cards_through_the_dashboard(client, board, alice, bob):
    """Bob may not open Alice's metric, but the dashboard shared with him draws
    it, and its rows open by the card's place; the dataset's own access tier
    still holds (a staff-only dataset stays hidden from him)."""
    Metric(key="sh_staff", name="Staff only", dataset=DS_STAFF, owner=alice).save()
    board.layout.append({"id": "c2", "type": "metric", "metric": "sh_staff"})
    board.save()
    set_sharing(board, actor=alice, add=["bob"])
    client.force_login(bob)
    assert client.get("/smallstack/dashboards/m/sh_req/").status_code == 404  # the metric itself: not his
    cell = client.get("/smallstack/dashboards/d/alice-ops/cells/c1/").content.decode()
    assert ">5<" in cell and 'hx-get="/smallstack/dashboards/d/alice-ops/cards/c1/rows/' in cell  # by its place
    rows = client.get("/smallstack/dashboards/d/alice-ops/cards/c1/rows/", HTTP_HX_REQUEST="true").content.decode()
    assert "<strong>5 rows</strong>" in rows
    assert "access" in client.get("/smallstack/dashboards/d/alice-ops/cells/c2/").content.decode()  # staff data: no
    page = client.get("/smallstack/dashboards/d/alice-ops/").content.decode()
    assert "data-metric-url=" not in page  # the card menu doesn't offer a metric he can't open
    # The owner's own view still opens the metric's rows the usual way.
    client.force_login(alice)
    own = client.get("/smallstack/dashboards/d/alice-ops/cells/c1/").content.decode()
    assert 'hx-get="/smallstack/dashboards/m/sh_req/rows/' in own
    # Shared with you, on Bob's My dashboards; the overview lists it as shared by Alice.
    client.force_login(bob)
    mine = client.get("/smallstack/dashboards/mine/").content.decode()
    assert "Shared with you" in mine and "Alice ops" in mine and "Alice Ames" in mine
    assert "Shared by alice" in client.get("/smallstack/dashboards/").content.decode()


def test_sharing_over_mcp_and_rest(client, board, alice, bob, carol):
    assert _call("dashboard_share", {"dashboard": "alice-ops"}, alice) == {
        "ok": True, "everyone": False, "people": [], "audience": "Personal"
    }
    out = _call("dashboard_share", {"dashboard": "alice-ops", "add": ["bob", "zed"], "everyone": True}, alice)
    assert out["everyone"] and out["people"] == [{"username": "bob", "name": "Bob"}] and out["unknown"] == ["zed"]
    assert "error" in _call("dashboard_share", {"dashboard": "alice-ops", "add": ["carol"]}, bob)  # not his to share
    assert "error" in _call("dashboard_share", {"dashboard": "alice-ops"}, carol)  # a viewer can't even ask
    client.force_login(carol)
    data = client.get(f"/smallstack/api/dashboards/boards/{board.pk}/").json()
    assert data["sharing"] == {"everyone": True, "people": ["bob"]}


def test_the_table_view_offers_edit_and_delete_only_where_the_row_allows(client, alice, bob):
    """Staff see every personal row but change only their own; the table's
    icons agree with what the edit route accepts (the library view already did)."""
    from apps.dashboards.models import Playlist

    staff = User.objects.create_user("sstaff", password="x", is_staff=True)
    Playlist(name="Alice's", slug="alices", owner=alice).save()
    Playlist(name="Everyone's", slug="everyones").save()
    client.force_login(staff)
    html = client.get("/smallstack/dashboards/playlists/?display=table").content.decode()
    mine = Playlist.objects.get(slug="alices").pk
    ours = Playlist.objects.get(slug="everyones").pk
    assert f"/smallstack/dashboards/playlists/{ours}/edit/" in html  # the ownerless one: staff edit it
    assert f"/smallstack/dashboards/playlists/{mine}/edit/" not in html  # Alice's: no icon, as no permission
    assert f"/smallstack/dashboards/playlists/{mine}/delete/" not in html
    library = client.get("/smallstack/dashboards/playlists/?display=library").content.decode()
    assert "Personal · alice" in library and f"/playlists/{mine}/edit/" not in library  # whose, and no icon
    assert client.get(f"/smallstack/dashboards/playlists/{mine}/edit/").status_code == 403  # what the icon led to


def test_sharing_with_someone_who_cant_read_the_data_says_so(alice, bob):
    # An agent shared a dashboard "so she can look at it" and got ok:true; the
    # person then saw only dashes. The reply now names the cards they can't read.
    from apps.dashboards.tests.test_dashboards import DS_STAFF

    _seed()
    Metric(key="sh_staff", name="Staff only", dataset=DS_STAFF, owner=alice).save()
    Metric(key="sh_open", name="Open", dataset=DS_AUTH, owner=alice).save()
    d = Dashboard(
        name="Mixed",
        slug="mixed",
        owner=alice,
        layout=[
            {"id": "a", "type": "metric", "metric": "sh_staff", "x": 0, "w": 3},
            {"id": "b", "type": "metric", "metric": "sh_open", "x": 3, "w": 3},
        ],
    )
    d.save()
    out = set_sharing(d, actor=alice, add=["bob"])
    assert out["cant_read"] == {"bob": ["Staff only"]}
    assert "bob can't read 1 of the cards (Staff only)" in out["warning"]
    assert "cant_read" not in set_sharing(d, actor=alice, add=["bob"])  # nobody new added


def test_staff_search_the_share_dialog_by_any_part_of_a_name(client, alice, bob):
    alice.is_staff = True
    alice.save()
    d = Dashboard(name="Staff board", slug="staff-board", owner=alice, layout=[])
    d.save()
    client.force_login(alice)
    found = client.get("/smallstack/dashboards/d/staff-board/share/?q=bo", HTTP_HX_REQUEST="true").content.decode()
    assert 'name="add" value="bob"' in found


def test_a_person_is_told_once_however_often_they_are_added(board, alice, bob):
    set_sharing(board, actor=alice, add=["bob"])
    set_sharing(board, actor=alice, remove=["bob"])
    set_sharing(board, actor=alice, add=["bob"])
    assert Notification.objects.filter(recipient=bob, kind="dashboards.shared").count() == 1
