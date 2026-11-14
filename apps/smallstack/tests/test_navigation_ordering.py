"""Admin nav is listed A–Z; every other section keeps its explicit `order`.

The admin section is a tool drawer — a dozen unrelated utilities contributed by
whichever apps are installed, with no workflow sequence to preserve. It was
hand-numbered, which meant every new app picked a number, the numbers collided
(Status and Explorer both sat at 20, so their relative order fell out of
INSTALLED_APPS ordering), and the list drifted out of alphabetical whenever
anything was added or relabelled.

Sorting in the registry rather than renumbering twelve `apps.py` files is what
keeps it A–Z as apps come and go, including apps a downstream project adds.
"""

from __future__ import annotations

import pytest

from apps.smallstack.navigation import ALPHABETICAL_SECTIONS, _NavItem, _sort_key, nav


def _labels(section: str) -> list[str]:
    items = [i for i in nav._items if i.section == section]
    return [i.label for i in sorted(items, key=_sort_key)]


def _item(label: str, *, section: str = "admin", order: int = 0) -> _NavItem:
    return _NavItem(
        section=section,
        label=label,
        url_name="x",
        url_args=None,
        url_kwargs=None,
        icon_svg="",
        auth_required=False,
        staff_required=False,
        order=order,
        parent=None,
        zone="smallstack",
        active_prefix=None,
    )


def test_admin_section_is_alphabetical():
    labels = _labels("admin")
    assert labels == sorted(labels, key=str.casefold)


def test_admin_section_is_not_empty():
    """Guard the guard: an empty list would satisfy the sort assertion."""
    assert len(_labels("admin")) >= 10


def test_sort_is_case_insensitive():
    """"API Health" belongs next to "Activity", not ahead of every lowercase label.

    A naive `sorted()` on the raw string puts every capitalised label first,
    because 'P' < 'c' in ASCII — which reads as broken in a menu.
    """
    items = [_item("Activity"), _item("API Health"), _item("Backups")]
    assert [i.label for i in sorted(items, key=_sort_key)] == [
        "Activity",
        "API Health",
        "Backups",
    ]


def test_order_is_ignored_in_alphabetical_sections():
    """A stale `order=` left in an app's register() call must not reorder anything."""
    items = [_item("Zebra", order=0), _item("Alpha", order=99)]
    assert [i.label for i in sorted(items, key=_sort_key)] == ["Alpha", "Zebra"]


def test_other_sections_still_honour_order():
    items = [_item("Zebra", section="main", order=1), _item("Alpha", section="main", order=2)]
    assert [i.label for i in sorted(items, key=_sort_key)] == ["Zebra", "Alpha"]


@pytest.mark.parametrize("section", sorted(ALPHABETICAL_SECTIONS))
def test_declared_alphabetical_sections_actually_sort_that_way(section):
    items = [_item("Zebra", section=section, order=0), _item("Alpha", section=section, order=1)]
    assert [i.label for i in sorted(items, key=_sort_key)] == ["Alpha", "Zebra"]


def test_a_newly_registered_tool_lands_in_place_without_renumbering():
    """The point of sorting in the registry: no app has to pick a number.

    A new tool named "Billing" must slot between "Backups" and "Dashboard" with
    order left at its default.
    """
    live = [i for i in nav._items if i.section == "admin"]
    merged = sorted([*live, _item("Billing")], key=_sort_key)
    labels = [i.label for i in merged]
    assert labels == sorted(labels, key=str.casefold)
    assert labels[labels.index("Billing") - 1] == "Backups"
