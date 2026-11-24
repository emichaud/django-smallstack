"""The Access user list: filter pills with counts, sortable columns, search,
rows per page — every control a link or GET, the state in the address."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.smallstack.models import APIToken

pytestmark = pytest.mark.django_db

User = get_user_model()


def rows(html: str) -> list[str]:
    """The usernames in the table, in order."""
    return re.findall(r'class="users-name">([^<]+)</a>', html)


@pytest.fixture
def people(db, root, staffer, alice, readers):
    alice.groups.add(readers)
    # Two direct permissions: more than the staffer fixture's one, so "-direct" puts alice first.
    alice.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="accounts", codename__in=["view_user", "change_user"])
    )
    User.objects.filter(pk=alice.pk).update(last_login=timezone.now() - timedelta(days=3))
    User.objects.filter(pk=root.pk).update(last_login=timezone.now() - timedelta(days=1))
    gone = User.objects.create_user("gone", password="p", is_active=False)
    APIToken.create_token(user=root, name="t")
    return {"root": root, "staffer": staffer, "alice": alice, "gone": gone}


def test_the_pills_carry_counts_and_filter(client, people, staffer):
    client.force_login(staffer)
    html = client.get(reverse("access:users")).content.decode()
    # Active 3 (root, staffer, alice), Staff 2, Deactivated 1, All 4 — the pills say so.
    assert re.search(r'Active <span class="filter-count">3</span>', html)
    assert re.search(r'Staff <span class="filter-count">2</span>', html)
    assert re.search(r'Deactivated <span class="filter-count">1</span>', html)
    assert re.search(r'All <span class="filter-count">4</span>', html)
    assert rows(html) == ["alice", "root", "staffer"] and "gone" not in html
    assert rows(client.get(reverse("access:users") + "?show=staff").content.decode()) == ["root", "staffer"]
    assert rows(client.get(reverse("access:users") + "?show=inactive").content.decode()) == ["gone"]
    assert len(rows(client.get(reverse("access:users") + "?show=all").content.decode())) == 4
    assert "deactivated" in client.get(reverse("access:users") + "?show=all").content.decode()
    # An unknown filter falls back to active rather than erroring.
    assert rows(client.get(reverse("access:users") + "?show=wat").content.decode()) == ["alice", "root", "staffer"]


def test_the_columns_sort_both_ways_with_never_last(client, people, staffer):
    client.force_login(staffer)
    User.objects.filter(pk=staffer.pk).update(last_login=None)  # force_login stamped it; the session stays
    url = reverse("access:users")
    assert rows(client.get(url + "?ordering=-last_login").content.decode()) == ["root", "alice", "staffer"]
    assert rows(client.get(url + "?ordering=last_login").content.decode()) == ["alice", "root", "staffer"]
    assert rows(client.get(url + "?ordering=-direct").content.decode())[0] == "alice"
    assert rows(client.get(url + "?ordering=-tokens").content.decode())[0] == "root"
    assert rows(client.get(url + "?ordering=role").content.decode())[0] == "root"  # superuser first
    assert rows(client.get(url + "?ordering=-username").content.decode()) == ["staffer", "root", "alice"]
    html = client.get(url + "?ordering=-last_login").content.decode()
    assert 'aria-sort="descending"' in html and html.count("is-sorted") == 1
    # The sorted column's next click reverses; an unknown key is the default.
    assert "?ordering=last_login" in html
    assert rows(client.get(url + "?ordering=nope").content.decode()) == ["alice", "root", "staffer"]


def test_search_and_rows_per_page(client, people, staffer):
    client.force_login(staffer)
    url = reverse("access:users")
    assert rows(client.get(url + "?q=Readers").content.decode()) == ["alice"]  # by group name
    html = client.get(url + "?q=zzz").content.decode()
    assert "No account matches" in html and "show=all" in html
    for i in range(20):
        User.objects.create_user(f"u{i:02d}", password="p")
    assert len(rows(client.get(url + "?per_page=15").content.decode())) == 15
    assert len(rows(client.get(url + "?per_page=25").content.decode())) == 23
    assert len(rows(client.get(url + "?per_page=999").content.decode())) == 15  # not a choice: the default
    html = client.get(url).content.decode()
    assert "Rows per page" in html and 'name="per_page"' in html
