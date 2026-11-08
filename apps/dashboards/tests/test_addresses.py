"""Addresses (``slug``) of dashboards, reports, playlists and goal lists: made
from the name, never asked for, stable when the name changes, and changed on
purpose only by an administrator (a superuser, or the ``admin`` group); everyone
else, staff included, sees it read-only."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.dashboards.forms import DashboardForm
from apps.dashboards.models import (
    ADDRESS_ADMIN_GROUP,
    Dashboard,
    GoalList,
    Playlist,
    Report,
    can_change_address,
    free_slug,
)

pytestmark = pytest.mark.django_db

User = get_user_model()

PAGES = [
    ("boards", Dashboard, {"layout": "[]"}),
    ("reports", Report, {"items": "[]"}),
    ("playlists", Playlist, {"items": "[]", "seconds": "30"}),
    ("goals", GoalList, {"sections": "[]"}),
]


@pytest.fixture
def staff(client):
    user = User.objects.create_user("ad-staff", password="x", is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def admin(client):
    user = User.objects.create_user("ad-admin", password="x", is_staff=True, is_superuser=True)
    client.force_login(user)
    return user


@pytest.fixture
def member(client):
    user = User.objects.create_user("ad-member", password="x")
    client.force_login(user)
    return user


def test_an_address_is_the_name_then_the_name_and_a_number():
    assert free_slug(Dashboard, "Site health!") == "site-health"
    Dashboard(name="Site health", slug="site-health").save()
    Dashboard(name="Site health", slug="site-health-2").save()
    assert free_slug(Dashboard, "Site Health") == "site-health-3"
    assert free_slug(Report, "Site health") == "site-health"  # each kind has its own addresses
    # A name with nothing an address can keep takes the kind's own word.
    assert free_slug(Dashboard, "!!!") == "dashboard" and free_slug(GoalList, "日本語") == "goal-list"
    assert len(free_slug(Dashboard, "x" * 200)) <= 80


@pytest.mark.parametrize(("base", "model", "extra"), PAGES)
def test_the_new_form_asks_for_no_address_and_makes_one_from_the_name(client, staff, base, model, extra):
    url = f"/smallstack/dashboards/{base}/new/"
    html = client.get(url).content.decode()
    assert 'name="slug"' not in html and "df-slug" not in html and ">Address<" not in html
    assert "Filled in from the name" not in html and "Changing it breaks" not in html  # nothing left of the old field
    assert html.count("<div") == html.count("</div>")
    posted = {"name": "Weekly Ops Review", "visibility": "shared", **extra}
    assert client.post(url, posted).status_code == 302
    assert client.post(url, posted).status_code == 302  # the same name again is no problem
    assert sorted(model.objects.values_list("slug", flat=True)) == ["weekly-ops-review", "weekly-ops-review-2"]


def test_an_address_someone_names_is_kept(staff):
    form = DashboardForm({"name": "Site health", "slug": "ops", "visibility": "shared", "layout": "[]"}, user=staff)
    assert form.is_valid(), form.errors
    assert form.save().slug == "ops"  # an agent or the API may still name one
    again = DashboardForm({"name": "Other", "slug": "ops", "visibility": "shared", "layout": "[]"}, user=staff)
    assert not again.is_valid() and "slug" in again.errors  # a taken one is refused, not quietly renumbered


@pytest.mark.parametrize(("base", "model", "extra"), PAGES)
def test_renaming_keeps_the_address(client, staff, base, model, extra):
    client.post(f"/smallstack/dashboards/{base}/new/", {"name": "First name", "visibility": "shared", **extra})
    obj = model.objects.get(slug="first-name")
    posted = {"name": "A new name", "visibility": "shared", **{k: v for k, v in extra.items() if k != "layout"}}
    assert client.post(f"/smallstack/dashboards/{base}/{obj.pk}/edit/", posted).status_code == 302
    obj.refresh_from_db()
    assert (obj.name, obj.slug) == ("A new name", "first-name")


def test_the_settings_page_shows_the_address_read_only_to_a_member(client, member):
    mine = Dashboard(name="Mine", slug="mine", owner=member, created_by=member)
    mine.save()
    url = f"/smallstack/dashboards/boards/{mine.pk}/edit/"
    html = client.get(url).content.decode()
    assert "/smallstack/dashboards/d/mine/</code>" in html
    assert 'name="slug"' not in html and "Change the address" not in html and "stays the same if you rename it" in html
    # Posting one anyway is refused, not ignored.
    response = client.post(url, {"name": "Mine", "slug": "theirs", "visibility": "personal"})
    assert response.status_code == 200 and "Only an administrator can change an address" in response.content.decode()
    mine.refresh_from_db()
    assert mine.slug == "mine"


def test_staff_who_are_not_administrators_see_it_read_only(client, staff):
    shared = Dashboard(name="Ops", slug="ops")
    shared.save()
    url = f"/smallstack/dashboards/boards/{shared.pk}/edit/"
    html = client.get(url).content.decode()
    assert "/smallstack/dashboards/d/ops/</code>" in html and "Only an administrator can change it" in html
    assert 'name="slug"' not in html and "Change the address" not in html
    response = client.post(url, {"name": "Ops", "slug": "operations", "visibility": "shared"})
    assert response.status_code == 200 and "Only an administrator can change an address" in response.content.decode()
    shared.refresh_from_db()
    assert shared.slug == "ops"


def test_who_counts_as_an_administrator(staff):
    assert not can_change_address(staff) and not can_change_address(None)
    staff.groups.add(Group.objects.create(name=ADDRESS_ADMIN_GROUP))
    assert can_change_address(User.objects.get(pk=staff.pk))
    assert can_change_address(User(username="root", is_superuser=True))


def test_an_administrator_can_change_an_address_on_purpose(client, admin):
    shared = Dashboard(name="Ops", slug="ops")
    shared.save()
    url = f"/smallstack/dashboards/boards/{shared.pk}/edit/"
    html = client.get(url).content.decode()
    assert "/smallstack/dashboards/d/ops/</code>" in html and "Change the address" in html
    assert 'name="slug" value="ops"' in html and "breaks bookmarks and links" in html
    assert client.post(url, {"name": "Ops", "slug": "operations", "visibility": "shared"}).status_code == 302
    shared.refresh_from_db()
    assert shared.slug == "operations"
    taken = Dashboard(name="Other", slug="other")
    taken.save()
    response = client.post(url, {"name": "Ops", "slug": "other", "visibility": "shared"})
    assert response.status_code == 200 and "<details" in response.content.decode()
    assert 'class="df-address-change" open' in response.content.decode()  # the mistake is where they can see it


def test_a_duplicate_gets_an_address_of_its_own(client, staff):
    Dashboard(name="Ops", slug="ops").save()
    posted = {"name": "Ops (copy)", "visibility": "personal", "layout": "[]"}
    assert client.post("/smallstack/dashboards/boards/new/?from=ops", posted).status_code == 302
    assert Dashboard.objects.get(name="Ops (copy)").slug == "ops-copy"
