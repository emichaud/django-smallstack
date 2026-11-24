"""The Changes page: family pills, sortable columns, rows per page, and an
export that takes the same filter. The other pages' event tables stay plain."""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.access.context import acting_as
from apps.access.models import AccessEvent

pytestmark = pytest.mark.django_db

User = get_user_model()


def kinds(html: str) -> list[str]:
    return re.findall(r'<td class="nowrap event-kind(?: event-grant)?">([^<]+)</td>', html)


#: The shipped groups' migrate-time events are in the log too; alice's are the ones the tests read.
ALICE = "&who=alice"


@pytest.fixture
def log(root, alice, readers):
    with acting_as(root, "web:/x/"):
        alice.groups.add(readers)  # group_added (a grant)
        alice.groups.remove(readers)  # group_removed
        readers.permissions.add(*[])  # nothing
        alice.is_active = False
        alice.save()  # deactivated (+ sessions_ended / token events as the signals decide)
    return AccessEvent.objects.all()


def test_the_pills_filter_by_family_and_a_single_kind_still_works(client, staffer, log):
    client.force_login(staffer)
    url = reverse("access:events")
    html = client.get(url).content.decode()
    assert "Grants" in html and "Removals" in html and "Tokens &amp; sessions" in html and "Export CSV" in html
    assert kinds(client.get(url + "?kind=grants" + ALICE).content.decode()) == ["Added to group"]
    removals = kinds(client.get(url + "?kind=removals" + ALICE).content.decode())
    assert "Removed from group" in removals and "Account deactivated" in removals and "Added to group" not in removals
    assert "Added to group" not in kinds(client.get(url + "?kind=accounts" + ALICE).content.decode())
    single = client.get(url + "?kind=group_removed" + ALICE).content.decode()
    assert (
        kinds(single) == ["Removed from group"]
        and 'class="filter-toggle active"' in single
        and ">Removed from group<" in single
    )
    assert "No change matches" in client.get(url + "?who=nobody").content.decode()


def test_columns_sort_and_the_default_is_newest_first(client, staffer, log):
    client.force_login(staffer)
    url = reverse("access:events")
    newest_first = kinds(client.get(url + "?who=alice").content.decode())
    # alice's first event is her creation; her last is the deactivation.
    assert newest_first[-1] == "Account created" and newest_first[0] == "Account deactivated"
    assert kinds(client.get(url + "?ordering=at" + ALICE).content.decode())[0] == "Account created"
    by_kind = kinds(client.get(url + "?ordering=kind" + ALICE).content.decode())
    assert by_kind == sorted(
        by_kind, key=lambda label: AccessEvent.Kind(dict((v, k) for k, v in AccessEvent.Kind.choices)[label])
    )
    html = client.get(url + "?ordering=-at").content.decode()
    assert 'aria-sort="descending"' in html and html.count("is-sorted") == 1
    assert kinds(client.get(url + "?ordering=nope" + ALICE).content.decode()) == newest_first


def test_rows_per_page_and_the_export_take_the_filter(client, staffer, log):
    client.force_login(staffer)
    url = reverse("access:events")
    assert "Rows per page" in client.get(url + "?per_page=15").content.decode() or AccessEvent.objects.count() <= 15
    csv = b"".join(client.get(reverse("access:events_csv") + "?kind=grants" + ALICE).streaming_content).decode()
    assert csv.count("\n") == 2 and "group_added" in csv  # the header and the one grant
    csv = b"".join(client.get(reverse("access:events_csv") + "?kind=removals&ordering=at").streaming_content).decode()
    assert "group_removed" in csv and "group_added" not in csv


def test_the_other_pages_tables_stay_plain(client, staffer, root, readers, log):
    client.force_login(staffer)
    for name, kwargs in (("index", {}), ("group_detail", {"pk": readers.pk}), ("user_detail", {"pk": root.pk})):
        html = client.get(reverse(f"access:{name}", kwargs=kwargs)).content.decode()
        assert "sort-link" not in html and '<th scope="col">When</th>' in html, name
